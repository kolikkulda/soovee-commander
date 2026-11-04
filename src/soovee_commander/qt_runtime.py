"""Keep Qt discovery working when a macOS cloud folder hides .venv files."""
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QCoreApplication, QDir, QLibraryInfo


def prepare_plugins():
    if sys.platform != "darwin":
        return None
    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    platforms = plugins / "platforms"
    if QDir(str(platforms)).entryList(QDir.Filter.Files) or not platforms.is_dir():
        return None
    if not list(platforms.glob("*.dylib")):
        return None
    # Copy bytes, not Finder flags or xattrs. Do not modify the user's environment.
    temporary = tempfile.TemporaryDirectory(prefix="stereo-qt-", ignore_cleanup_errors=True)
    shutil.copytree(plugins, temporary.name, dirs_exist_ok=True, copy_function=shutil.copyfile)
    QCoreApplication.addLibraryPath(temporary.name)
    return temporary
