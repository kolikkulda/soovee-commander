"""Coalesced change notifications for the folder a panel currently shows.

Only the visible folder of each panel is watched, never a whole tree, so the
cost stays constant. Systems report added, removed and renamed items; changes
inside an existing file are caught by the refresh when the application
becomes active again.

macOS and Linux use the system notifications (kqueue with O_EVTONLY / inotify),
which never keep a folder busy. On Windows a change notification needs an open
directory handle, and NTFS then refuses to rename or delete that folder and
all of its parents ("folder in use"), even from Explorer. Windows therefore
polls the folder's modification time, which NTFS updates whenever an entry is
added, removed or renamed. Network drives are not polled; returning to the
application refreshes them.
"""
import os

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer

from .diagnostic_log import logger

POLLING = os.name == "nt"


def _network_drive(path):
    if not POLLING:
        return False
    import ctypes
    root = os.path.splitdrive(os.path.abspath(path))[0]
    if root.startswith("\\\\"):
        return True  # UNC share
    return ctypes.windll.kernel32.GetDriveTypeW(root + "\\") == 4  # DRIVE_REMOTE


def _windows_stamp(path):
    """Live last-write time and identity of a folder, or None when it is gone.

    os.stat may answer from the copy NTFS keeps in the parent folder's index
    (GetFileInformationByName), which is refreshed lazily. Asking the folder
    itself through a momentary handle returns the current value; the handle
    shares read, write and delete, and is closed immediately, so nothing is
    kept busy.
    """
    import ctypes
    from ctypes import wintypes

    class Information(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME), ("accessed", wintypes.FILETIME),
                    ("written", wintypes.FILETIME), ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD), ("index_high", wintypes.DWORD),
                    ("index_low", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(Information)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(path, 0x80, 0x7, None, 3, 0x02000000, None)  # read attributes, share all, open existing, directory
    if handle in (None, wintypes.HANDLE(-1).value):
        return None
    try:
        info = Information()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            return None
        written = info.written.dwHighDateTime << 32 | info.written.dwLowDateTime
        return written, info.index_high << 32 | info.index_low
    finally:
        kernel32.CloseHandle(handle)


class FolderWatcher(QObject):
    DELAY_MS = 300
    POLL_MS = 1500

    def __init__(self, parent, callback, polling=POLLING):
        super().__init__(parent)
        self.callback = callback
        self.polling = polling
        self.path = None
        self.signature = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._changed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.DELAY_MS)
        self.timer.timeout.connect(self._fire)
        self.poll = QTimer(self)
        self.poll.setInterval(self.POLL_MS)
        self.poll.timeout.connect(self._check)

    def _stat(self):
        if self.polling:
            # Folder timestamps are not refreshed reliably everywhere (NTFS caches
            # them); the list of names always is. One shown folder is cheap to list.
            try:
                stamp = _windows_stamp(self.path) if os.name == "nt" else None
            except Exception:  # A failing timestamp query must not stop name-based polling.
                logger.exception('Folder timestamp query failed')
                stamp = None
            try:
                with os.scandir(self.path) as entries:
                    names = sorted(entry.name for entry in entries)
            except OSError:
                return None
            return stamp, len(names), hash(tuple(names))
        try:
            info = os.stat(self.path)
            return info.st_mtime_ns, info.st_ino
        except OSError:
            return None

    def watch(self, path):
        path = os.path.normpath(path) if path else None
        active = self.poll.isActive() if self.polling else bool(self.watcher.directories())
        if path == self.path and (path is None or active):
            return
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.poll.stop()
        self.timer.stop()
        self.path = path
        if not path:
            return
        if self.polling:
            if not _network_drive(path):
                self.signature = self._stat()
                self.poll.start()
        elif not self.watcher.addPath(path):
            logger.info('Folder change notifications unavailable for %s', path)

    def _check(self):
        signature = self._stat()
        if signature != self.signature:
            self.signature = signature
            self.timer.start()

    def _changed(self, path):
        if self.path and os.path.normpath(path) == self.path:
            self.timer.start()  # Bursts such as copying many files become one refresh.

    def _fire(self):
        if not self.polling and not self.watcher.directories() and self.path:
            # The folder was removed or renamed; the system dropped the watch.
            self.watcher.addPath(self.path) if os.path.isdir(self.path) else None
        self.callback()
