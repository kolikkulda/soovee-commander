"""Mounted-volume snapshots. Call the readers outside the GUI thread."""
from dataclasses import dataclass
import os

from PySide6.QtCore import QStorageInfo


@dataclass(frozen=True)
class VolumeInfo:
    name: str
    root: str
    total: int | None = None
    free: int | None = None
    available: int | None = None
    readonly: bool = False
    filesystem: str = ""

    @property
    def used(self):
        return self.total - self.free if self.total is not None else None

    @property
    def percent(self):
        return round(100 * self.used / self.total) if self.total else 0


def volume_snapshot(storage):
    root = storage.rootPath()
    if not storage.isValid() or not storage.isReady():
        return None
    name = storage.displayName() or root
    if os.name == "nt" and root.rstrip("/\\").casefold() not in name.casefold():
        name += " (" + root.rstrip("/\\") + ")"
    total, free, available = storage.bytesTotal(), storage.bytesFree(), storage.bytesAvailable()
    if total <= 0 or not 0 <= available <= free <= total:
        total = free = available = None
    return VolumeInfo(name, root, total, free, available, storage.isReadOnly(),
                      bytes(storage.fileSystemType()).decode("ascii", errors="replace"))


def read_volume(path):
    return volume_snapshot(QStorageInfo(path))


def read_volumes():
    volumes = []
    for storage in QStorageInfo.mountedVolumes():
        root = storage.rootPath()
        if os.name != "nt" and root != "/" and not root.startswith("/Volumes/"):
            continue
        if (info := volume_snapshot(storage)) is not None:
            volumes.append(info)
    return tuple(volumes)
