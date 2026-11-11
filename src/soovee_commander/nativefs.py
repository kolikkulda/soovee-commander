"""OS primitives for fast, non-overwriting local moves."""
import ctypes
import errno
import os
import sys
from pathlib import Path


def is_junction(path):
    # Older Android Python has no Windows-only Path.is_junction method.
    return os.name == 'nt' and Path(path).is_junction()


def rename_no_replace(source, destination):
    """Return False when the filesystem needs copy/delete, never clobber a target."""
    if os.name == "nt":
        try:
            os.rename(source, destination)  # Windows rename rejects existing targets.
            return True
        except OSError as exc:
            if exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17:
                return False
            raise
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform in ("darwin", "ios", "tvos"):
        function = library.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = function(os.fsencode(source), os.fsencode(destination), 0x4)  # RENAME_EXCL
    elif hasattr(library, "renameat2"):
        function = library.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = function(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    else:
        return False
    if result == 0:
        return True
    error = ctypes.get_errno()
    # SMB and other network shares: macOS reports ENOTSUP (45), not EOPNOTSUPP (102).
    if error in (errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL):
        return False
    raise OSError(error, os.strerror(error), str(destination))


def rename_at_no_replace(source_dir, source, destination_dir, destination):
    """Rename between directory descriptors without replacing an existing name.

    Returns False when the filesystem has no atomic no-replace rename; the caller
    then checks for the target itself.
    """
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform in ("darwin", "ios", "tvos") and hasattr(library, "renameatx_np"):
        function = library.renameatx_np
        flags = 0x4  # RENAME_EXCL
    elif hasattr(library, "renameat2"):
        function = library.renameat2
        flags = 1  # RENAME_NOREPLACE
    else:
        return False
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if function(source_dir, os.fsencode(source), destination_dir, os.fsencode(destination), flags) == 0:
        return True
    error = ctypes.get_errno()
    if error in (errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL):
        return False
    raise OSError(error, os.strerror(error), destination)


class _AttrList(ctypes.Structure):
    _fields_ = [("bitmapcount", ctypes.c_ushort), ("reserved", ctypes.c_uint16), ("commonattr", ctypes.c_uint32),
                ("volattr", ctypes.c_uint32), ("dirattr", ctypes.c_uint32), ("fileattr", ctypes.c_uint32),
                ("forkattr", ctypes.c_uint32)]


_ATTR_CMN_ADDEDTIME = 0x10000000
_ATTR_CMN_RETURNED_ATTRS = 0x80000000
_LAST_USED = b"com.apple.lastuseddate#PS"
_darwin = None


def _darwin_library():
    global _darwin
    if _darwin is None:
        library = ctypes.CDLL(None, use_errno=True)
        library.getattrlist.argtypes = [ctypes.c_char_p, ctypes.POINTER(_AttrList), ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint]
        library.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        library.getxattr.restype = ctypes.c_ssize_t
        _darwin = library
    return _darwin


def finder_dates(path):
    """macOS Finder dates: (Date Added, Date Last Opened); 0 when the system has none.

    Date Added changes when an item arrives in a folder (copy, move, download,
    extraction), unlike the content modification time those operations keep.
    Date Last Opened is the LaunchServices timestamp Finder shows; it is not
    the noisy POSIX access time.
    """
    if sys.platform != "darwin":
        return 0.0, 0.0
    library, encoded = _darwin_library(), os.fsencode(path)
    added = opened = 0.0
    request = _AttrList(5, 0, _ATTR_CMN_RETURNED_ATTRS | _ATTR_CMN_ADDEDTIME)
    buffer = (ctypes.c_uint8 * 64)()
    if library.getattrlist(encoded, ctypes.byref(request), buffer, len(buffer), 1) == 0:  # FSOPT_NOFOLLOW
        returned = int.from_bytes(bytes(buffer[4:8]), sys.byteorder)
        if returned & _ATTR_CMN_ADDEDTIME:
            seconds, nanoseconds = (int.from_bytes(bytes(buffer[offset:offset + 8]), sys.byteorder, signed=True) for offset in (24, 32))
            added = seconds + nanoseconds / 1e9
    stamp = (ctypes.c_uint8 * 16)()
    if library.getxattr(encoded, _LAST_USED, stamp, 16, 0, 1) == 16:  # XATTR_NOFOLLOW
        seconds, nanoseconds = (int.from_bytes(bytes(stamp[offset:offset + 8]), sys.byteorder, signed=True) for offset in (0, 8))
        opened = seconds + nanoseconds / 1e9
    return added, opened
