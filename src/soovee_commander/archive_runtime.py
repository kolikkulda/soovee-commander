"""Locate the native archive DLL bundled into Windows distributions."""
import os
from pathlib import Path
import sys

_dll_directory = None


def prepare_archive():
    global _dll_directory
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        folder = Path(sys._MEIPASS) / "archive_bin"
        dll = folder / "archive.dll"
        if dll.is_file():
            os.environ["LIBARCHIVE"] = str(dll)
            if _dll_directory is None:
                _dll_directory = os.add_dll_directory(str(folder))
