"""OS file URLs plus instance-local descriptors for archives/remote providers."""
from .i18n import tr
import json
from pathlib import Path
import struct
import uuid

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication
from .providers import LocalProvider

MIME = "application/x-stereo-files"


class FileClipboard:
    def __init__(self):
        self.token = None
        self.payload = None

    def put(self, provider, base, entries, cut=False):
        if not entries:
            return
        if cut and not getattr(provider, 'supports_delete', True):
            raise ValueError(tr('This device permits copying, but not moving or deleting files.'))
        if cut and provider.readonly:
            raise ValueError(tr('Files can only be copied from an archive.'))
        token = uuid.uuid4().hex
        data = QMimeData()
        data.setData(MIME, token.encode("ascii"))
        if isinstance(provider, LocalProvider):
            urls = [QUrl.fromLocalFile(provider.join(base, e.name)) for e in entries]
            data.setUrls(urls)
            data.setData("x-special/gnome-copied-files", (("cut" if cut else "copy") + "\n" + "\n".join(url.toString() for url in urls)).encode("utf-8"))
            data.setData("application/x-kde-cutselection", b"1" if cut else b"0")
            data.setData("Preferred DropEffect", struct.pack("<I", 2 if cut else 1))
        self.token, self.payload = token, (provider, base, list(entries), cut)
        QApplication.clipboard().setMimeData(data)

    def get(self):
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return []
        if self.token and bytes(mime.data(MIME)) == self.token.encode("ascii"):
            return [self.payload]
        if not mime.hasUrls():
            return []
        cut = bytes(mime.data("application/x-kde-cutselection")) == b"1" or bytes(mime.data("Preferred DropEffect")) == struct.pack("<I", 2)
        gnome = bytes(mime.data("x-special/gnome-copied-files"))
        cut = cut or gnome.startswith(b"cut\n")
        groups = {}
        for url in mime.urls():
            if not url.isLocalFile():
                raise ValueError(tr('The file clipboard accepts only local file:// URLs from other applications.'))
            path = Path(url.toLocalFile())
            if not path.is_absolute() or not path.name:
                raise ValueError(tr('Invalid clipboard path.'))
            groups.setdefault(str(path.parent), []).append(path.name)
        result = []
        provider = LocalProvider()
        for base, names in groups.items():
            existing = {e.name: e for e in provider.list(base)}
            entries = []
            for name in names:
                if name not in existing:
                    raise FileNotFoundError(str(Path(base) / name))
                entries.append(existing[name])
            result.append((provider, base, entries, cut))
        return result

    def clear_cut(self, token):
        mime = QApplication.clipboard().mimeData()
        if mime and token and bytes(mime.data(MIME)) == token.encode("ascii"):
            QApplication.clipboard().clear()
            self.payload = self.token = None
