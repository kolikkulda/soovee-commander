"""OS association discovery, callable on worker threads. No apps are launched here."""
import ctypes as C
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import plistlib
import sys


@dataclass(frozen=True)
class Application:
    path: str
    name: str


def application(path):
    p = Path(path)
    name = p.stem
    if sys.platform == "darwin" and p.suffix.lower() == ".app":
        try:
            with (p / "Contents" / "Info.plist").open("rb") as stream:
                info = plistlib.load(stream)
            name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or name
        except (OSError, ValueError, plistlib.InvalidFileException):
            pass
    return Application(str(p), str(name))


class MacApplications:
    def __init__(self):
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.ls = C.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
        def bind(lib, name, result, *args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, args
            return fn
        ptr, index = C.c_void_p, C.c_long
        self.release = bind(self.cf, "CFRelease", None, ptr)
        self.string = bind(self.cf, "CFStringCreateWithCString", ptr, ptr, C.c_char_p, C.c_uint32)
        self.string_out = bind(self.cf, "CFStringGetCString", C.c_bool, ptr, C.c_char_p, index, C.c_uint32)
        self.url = bind(self.cf, "CFURLCreateFromFileSystemRepresentation", ptr, ptr, C.c_char_p, index, C.c_bool)
        self.url_path = bind(self.cf, "CFURLCopyFileSystemPath", ptr, ptr, C.c_int)
        self.count = bind(self.cf, "CFArrayGetCount", index, ptr)
        self.item = bind(self.cf, "CFArrayGetValueAtIndex", ptr, ptr, index)
        self.default_url = bind(self.ls, "LSCopyDefaultApplicationURLForURL", ptr, ptr, C.c_uint32, ptr)
        self.default_type = bind(self.ls, "LSCopyDefaultApplicationURLForContentType", ptr, ptr, C.c_uint32, ptr)
        self.all_apps = bind(self.ls, "LSCopyApplicationURLsForURL", ptr, ptr, C.c_uint32)
        self.uti = bind(self.ls, "UTTypeCreatePreferredIdentifierForTag", ptr, ptr, ptr, ptr)

    def path(self, url):
        value = self.url_path(url, 0)
        if not value:
            return None
        try:
            buffer = C.create_string_buffer(32768)
            if self.string_out(value, buffer, len(buffer), 0x08000100):
                return buffer.value.decode("utf-8")
        finally:
            self.release(value)

    def make_url(self, path):
        raw = os.fsencode(os.path.abspath(path))
        return self.url(None, raw, len(raw), os.path.isdir(path))

    def default_for_extension(self, extension):
        # Content-type lookup deliberately ignores per-file Finder overrides.
        tag = self.string(None, b"public.filename-extension", 0x08000100)
        value = self.string(None, extension.lstrip(".").encode("utf-8"), 0x08000100)
        uti = None
        app = None
        try:
            uti = self.uti(tag, value, None)
            if uti:
                app = self.default_type(uti, 0xffffffff, None)
                path = self.path(app) if app else None
                return application(path) if path else None
        finally:
            for ref in (app, uti, value, tag):
                if ref:
                    self.release(ref)

    def for_file(self, path):
        url = self.make_url(path)
        default = apps = None
        result = []
        try:
            default = self.default_url(url, 0xffffffff, None)
            if default:
                value = self.path(default)
                if value:
                    result.append(application(value))
            apps = self.all_apps(url, 0xffffffff)
            if apps:
                for index in range(self.count(apps)):
                    value = self.path(self.item(apps, index))
                    if value and value not in {a.path for a in result}:
                        result.append(application(value))
            return result
        finally:
            for ref in (apps, default, url):
                if ref:
                    self.release(ref)


@lru_cache(maxsize=1)
def mac_api():
    return MacApplications()


def windows_association(extension, kind=2):
    from ctypes import wintypes as W
    fn = C.WinDLL("shlwapi").AssocQueryStringW
    fn.argtypes = [W.DWORD, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.LPWSTR, C.POINTER(W.DWORD)]
    fn.restype = C.c_long
    length = W.DWORD(32768)
    buffer = C.create_unicode_buffer(length.value)
    if fn(0, kind, extension, None, buffer, C.byref(length)) == 0:
        return buffer.value


def default_application(extension):
    if not extension:
        return None
    if sys.platform == "darwin":
        return mac_api().default_for_extension(extension)
    if sys.platform == "win32":
        path = windows_association(extension)
        name = windows_association(extension, 4)
        if path or name:
            return Application(path or "", name or Path(path).stem)
    return None


def applications_for_file(path):
    if sys.platform == "darwin":
        return mac_api().for_file(path)
    result = []
    ext = Path(path).suffix.lower()
    default = default_application(ext)
    if default and default.path:
        result.append(default)
    if sys.platform == "win32":
        import winreg
        # OpenWithProgids includes per-user and system registrations. Query the
        # executable through the association API; never execute registry command strings.
        for root, key in ((winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\OpenWithProgids"), (winreg.HKEY_CLASSES_ROOT, ext + r"\OpenWithProgids")):
            try:
                with winreg.OpenKey(root, key) as handle:
                    for index in range(winreg.QueryInfoKey(handle)[1]):
                        progid = winreg.EnumValue(handle, index)[0]
                        executable = windows_association(progid)
                        if executable and executable.casefold() not in {a.path.casefold() for a in result}:
                            result.append(Application(executable, windows_association(progid, 4) or Path(executable).stem))
            except OSError:
                pass
    return result
