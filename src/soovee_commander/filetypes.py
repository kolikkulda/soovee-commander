"""Fast filename-only classification; no per-row filesystem or application lookup."""
from functools import lru_cache
from pathlib import PurePosixPath
import sys

from PySide6.QtCore import QMimeDatabase
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtCore import Qt, QRectF

from .providers import is_archive
from .i18n import tr

GROUPS = {
    "image": ('Image', "#a83e91", "IMG", "jpg jpeg png gif webp avif heic heif bmp tif tiff svg ico raw cr2 nef dng psd xcf"),
    "video": ("Video", "#7754bf", "VID", "mp4 m4v mov mkv avi webm wmv mpg mpeg mts m2ts vob"),
    "audio": ('Audio', "#b65c20", "AUD", "mp3 m4a aac flac wav ogg opus aiff wma mid midi"),
    "pdf": ("PDF document", "#c43d46", "PDF", "pdf"),
    "document": ('Document', "#3267be", "DOC", "doc docx odt rtf pages epub mobi azw azw3 djvu"),
    "sheet": ('Spreadsheet', "#29844c", "XLS", "xls xlsx xlsm ods csv tsv numbers"),
    "slides": ('Presentation', "#bc6224", "PPT", "ppt pptx odp key"),
    "code": ('Source code', "#287b63", "<>", "py js ts tsx jsx html htm css scss c cpp h hpp rs go java swift kt cs rb php lua sh bash zsh ps1 bat cmd sql json yaml yml toml xml ini cfg conf"),
    "text": ("Text", "#476b97", "TXT", "txt md markdown log rst tex srt ass vtt"),
    "cad": ("3D / CAD", "#167e8c", "3D", "stl step stp obj glb gltf fbx blend 3mf iges igs dwg dxf fcstd scad sketchup skp"),
    "application": ('Application', "#4d65b4", "APP", "app exe msi com apk dmg pkg deb rpm appimage"),
    "playlist": ("Playlist", "#a36920", "LIST", "m3u m3u8 pls mpd"),
    "torrent": ("Torrent", "#6b7542", "TOR", "torrent"),
    "font": ('Font', "#805e93", "Aa", "ttf otf woff woff2"),
    "archive": ('Archive', "#9c6519", "ZIP", "zip rar 7z tar gz bz2 xz tgz tbz2 txz cab iso"),
    "file": ('File', "#697b90", "", ""),
}
EXTENSIONS = {extension: key for key, data in GROUPS.items() for extension in data[3].split()}


def extension(name):
    suffix = PurePosixPath(name).suffix.lower()
    return suffix if suffix != "." else ""


@lru_cache(maxsize=4096)
def kind(name, is_dir=False, is_link=False, packages=True):
    if is_link:
        return "link", tr("Symbolic link")
    if is_dir and not (packages and sys.platform == "darwin" and name.lower().endswith(".app")):
        return "folder", tr("Folder")
    ext = extension(name)[1:]
    group = "archive" if is_archive(name) else EXTENSIONS.get(ext, "file")
    label = tr(GROUPS[group][0])
    if group == "file" and ext:
        label = tr("{v0} file").format(v0=ext.upper())
    elif group not in ("application", "archive", "pdf") and ext:
        label += " · " + ext.upper()
    return group, label


@lru_cache(maxsize=4096)
def mime_name(name):
    return QMimeDatabase().mimeTypeForFile(name, QMimeDatabase.MatchMode.MatchExtension).name()


@lru_cache(maxsize=128)
def type_icon(group, logical_size=20):
    label, color, badge, _ = GROUPS.get(group, GROUPS["file"])
    logical_size = max(12, min(256, int(logical_size)))
    pixmap = QPixmap(logical_size * 2, logical_size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.scale(logical_size / 20, logical_size / 20)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(QRectF(3, 1.5, 14, 17), 1.5, 1.5)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(1, 8, 18, 9), 1, 1)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Arial", 5 if len(badge) > 2 else 6, QFont.Weight.Bold))
    painter.drawText(QRectF(1, 8, 18, 9), Qt.AlignmentFlag.AlignCenter, badge or "•")
    painter.end()
    return QIcon(pixmap)
