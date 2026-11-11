"""Filesystem adapters. Network connections belong to one operation/thread."""
from __future__ import annotations

import contextlib
import errno
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ftplib
import os
from pathlib import Path
import posixpath
import shutil
import ssl
import stat
import sys
import tarfile
import tempfile
from typing import BinaryIO, Callable
from threading import RLock, local
import uuid
import zipfile
import unicodedata
from .diagnostic_log import logger
from .nativefs import finder_dates as native_finder_dates, rename_no_replace

Progress = Callable[[int], None]


class _FTP_TLS(ftplib.FTP_TLS):
    @contextlib.contextmanager
    def transfercmd(self, cmd, rest=None):
        connection = super().transfercmd(cmd, rest)
        try:
            yield connection
        except BaseException:
            # ftplib normally unwraps TLS after its transfer loop. A canceled
            # progress callback bypasses that line, leaving some servers holding
            # the file open. Send close_notify before closing the data socket.
            if isinstance(connection, ssl.SSLSocket):
                with contextlib.suppress(OSError, ValueError):
                    connection.settimeout(2)
                    connection.unwrap()
            raise
        finally:
            connection.close()


class _SFTPChunkReader:
    """Drain bounded pipelined batches before exposing bytes to a cancelable reader."""
    def __init__(self, stream, size):
        self.stream, self.size, self.position = stream, size, 0

    def read(self, size):
        end = min(self.size, self.position + size)
        if end <= self.position:
            return b""
        chunks = [(offset, min(32768, end - offset)) for offset in range(self.position, end, 32768)]
        blocks = list(self.stream.readv(chunks, max_concurrent_prefetch_requests=16))
        data = b"".join(blocks)
        if len(data) != end - self.position:
            raise IOError('The remote file changed while reading or the transfer is incomplete.')
        self.position = end
        return data


class _StableLocalReader:
    def __init__(self, stream):
        self.stream = stream
        self.before = os.fstat(stream.fileno())

    def read(self, size):
        data = self.stream.read(size)
        if not data:
            after = os.fstat(self.stream.fileno())
            if (self.before.st_size, self.before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise IOError('The source file changed during transfer. The destination was not completed.')
        return data


def safe_name(name: str) -> str:
    if not name or name in (".", "..") or any(c in name for c in "/\\\0\r\n"):
        raise ValueError(f'Invalid name: {name!r}')
    if os.name == "nt" and (any(c in name for c in '<>:"|?*') or name.endswith((".", " "))
                            or name.split('.')[0].upper() in
                            {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                             *(f"LPT{i}" for i in range(1, 10))}):
        raise ValueError('This name is not valid on Windows.')
    return name


def pump(source: BinaryIO, target: BinaryIO, progress: Progress) -> None:
    while block := source.read(256 * 1024):
        target.write(block)
        progress(len(block))


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    size: int = 0
    modified: float = 0
    is_link: bool = False
    mode: int = 0
    created: float = 0
    accessed: float = 0
    owner: str = ""
    group: str = ""
    link_target: str = ""
    added: float = 0
    opened: float = 0


from functools import lru_cache

def copy_metadata(source, destination):
    """Times and permissions like shutil.copystat. Extended attributes are copied
    when allowed; Android's SELinux refuses them with EACCES, which copystat does
    not ignore, so fall back to mode and times only."""
    try:
        shutil.copystat(source, destination)
    except PermissionError:
        info = os.stat(source)
        try:
            os.chmod(destination, stat.S_IMODE(info.st_mode))
        except OSError:
            pass
        os.utime(destination, ns=(info.st_atime_ns, info.st_mtime_ns))


@lru_cache(maxsize=256)
def owner_name(uid, group=False):
    if os.name == "nt":
        return ""
    try:
        if group:
            import grp
            return grp.getgrgid(uid).gr_name
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (KeyError, ImportError):
        return str(uid)


class Provider:
    readonly = False
    label = ""

    def batch(self):
        return contextlib.nullcontext()

    def operation_progress(self, callback):
        pass

    @contextlib.contextmanager
    def open_reader(self, path):
        # FTP-to-remote fallback; local/archive sources override this with a stream.
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as stream:
            self.read_to(path, stream, lambda count: None)
            stream.seek(0)
            yield stream

    def join(self, path: str, name: str) -> str:
        return posixpath.join(path, safe_name(name))

    def parent(self, path: str) -> str:
        return posixpath.dirname(path.rstrip("/")) or "/"

    def exists(self, path: str) -> bool:
        parent, name = self.parent(path), posixpath.basename(path)
        return any(e.name == name for e in self.list(parent))


class LocalProvider(Provider):
    label = 'LOCAL DISK'

    def join(self, path: str, name: str) -> str:
        return str(Path(path) / safe_name(name))

    def parent(self, path: str) -> str:
        return str(Path(path).parent)

    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def list(self, path: str, *, fresh=False, finder_dates=False) -> list[Entry]:
        """finder_dates adds macOS Date Added/Last Opened (one extra syscall per item)."""
        result = []
        darwin_dates = finder_dates and sys.platform == "darwin"
        with os.scandir(path) as items:
            for item in items:
                try:
                    # NTFS enumeration metadata may lag behind updates made via
                    # another handle. Comparison snapshots need current stat data;
                    # ordinary panel listings retain the fast enumeration path.
                    info = os.stat(item.path, follow_symlinks=False) if fresh and os.name == 'nt' else item.stat(follow_symlinks=False)
                    created = getattr(info, "st_birthtime", info.st_ctime if os.name == "nt" else 0)
                    # Elsewhere the creation time is when a copy arrived, the closest Date Added.
                    added, opened = native_finder_dates(item.path) if darwin_dates else (created, info.st_atime)
                    result.append(Entry(item.name, item.is_dir(), info.st_size,
                                        info.st_mtime, item.is_symlink(), info.st_mode,
                                        created, info.st_atime, owner_name(info.st_uid), owner_name(info.st_gid, True),
                                        os.readlink(item.path) if item.is_symlink() else "", added, opened))
                except FileNotFoundError:
                    continue
        return result

    def read_to(self, path: str, output: BinaryIO, progress: Progress) -> None:
        with self.open_reader(path) as stream:
            pump(stream, output, progress)

    @contextlib.contextmanager
    def open_reader(self, path):
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Only regular files can be read. Links and special files are not supported.')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            after = os.fstat(stream.fileno())
            if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise IOError('The source file was replaced while opening it.')
            yield _StableLocalReader(stream)

    def write_from(self, path: str, source: BinaryIO, progress: Progress, overwrite=False) -> None:
        self.write_with(path, lambda output: pump(source, output, progress), progress, overwrite=overwrite)

    def write_with(self, path, producer, progress, metadata_path=None, modified=0, overwrite=False):
        # Publish only a completed file, without following an existing destination symlink.
        fd, temporary = tempfile.mkstemp(prefix=".stereo-", dir=str(Path(path).parent))
        try:
            with os.fdopen(fd, "wb") as output:
                producer(output)
            if metadata_path:
                copy_metadata(metadata_path, temporary)
            elif modified:
                os.utime(temporary, (modified, modified))
            progress(0)  # Cancellation is checked once more before publishing.
            # Prefer an exclusive native rename. Android SELinux can reject hard
            # links even inside a writable app-owned directory.
            try:
                if overwrite:
                    os.replace(temporary, path)
                    return
                if rename_no_replace(temporary, path):
                    return
                os.link(temporary, path)
            except OSError as exc:
                if exc.errno not in (errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV, errno.EMLINK):
                    raise
                # FAT/exFAT and some network shares have no hard links. Exclusive
                # creation still prevents overwrites; clean the new file on failure.
                with open(temporary, "rb") as staged:
                    output = open(path, "xb")
                    try:
                        with output:
                            pump(staged, output, lambda count: progress(0))
                        copy_metadata(temporary, path)
                    except BaseException:
                        os.unlink(path)
                        raise
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def mkdir(self, path: str) -> None:
        os.mkdir(path)

    def rename(self, path: str, destination: str) -> None:
        if rename_no_replace(path, destination):
            return
        # Network shares (SMB/NFS) and some disks have no atomic "rename unless the
        # target exists". Check the target first, then rename normally.
        if os.path.lexists(destination):
            same = False
            with contextlib.suppress(OSError):
                a, b = os.lstat(path), os.lstat(destination)
                same = (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)   # only the letter case changes
            if not same:
                raise FileExistsError('An item with this name already exists.')
        try:
            os.rename(path, destination)
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise OSError('This filesystem does not support safe renaming. Use copying instead.') from None
            raise

    def remove(self, path: str, entry: Entry) -> None:
        if entry.is_dir and not entry.is_link:
            shutil.rmtree(path)
        else:
            os.unlink(path)


ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".7z", ".rar")


def is_archive(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_SUFFIXES)


class ArchiveProvider(Provider):
    """Read an index and individual members, never extract an archive tree."""
    readonly = True
    label = 'ARCHIVE · READ ONLY'

    def __init__(self, filename: str, password: bytes | None = None):
        logger.info('Opening archive · path=%s', filename)
        self.filename = str(Path(filename).resolve())
        self._write_lock = RLock()
        self.password = password
        self.encrypted = False
        info = os.stat(self.filename)
        self.signature = info.st_size, info.st_mtime_ns
        self._local = local()
        self._zip = zipfile.is_zipfile(filename)
        self._extended = str(filename).lower().endswith((".7z", ".rar"))
        if self._zip:
            with zipfile.ZipFile(filename) as z:
                self._extended = any(i.compress_type == 99 for i in z.infolist())
                self.encrypted = any(i.flag_bits & 1 for i in z.infolist())
        self.members: dict[str, tuple[Entry, str]] = {}
        if self._extended:
            self._index_extended()
            return
        with self._open() as archive:
            items = archive.infolist() if self._zip else archive.getmembers()
            for item in items:
                raw = item.filename if self._zip else item.name
                normalized = raw
                while normalized.startswith("./"):
                    normalized = normalized[2:]
                # Reject traversal, Windows separators and absolute paths on every OS.
                parts = normalized.rstrip("/").split("/")
                if any(p in ("", ".", "..") or "\\" in p or ":" in p or "\0" in p
                       for p in parts):
                    continue
                name = "/".join(parts)
                if self._zip:
                    self.encrypted = self.encrypted or bool(item.flag_bits & 1)
                    link = stat.S_ISLNK(item.external_attr >> 16)
                    directory, size = item.is_dir(), item.file_size
                    modified = datetime(*item.date_time).timestamp()
                else:
                    link = item.issym() or item.islnk()
                    if not (item.isfile() or item.isdir() or link):
                        continue
                    directory, size, modified = item.isdir(), item.size, item.mtime
                self.members[name] = (Entry(parts[-1], directory, size, modified, link), raw)
                for i in range(1, len(parts)):
                    parent = "/".join(parts[:i])
                    self.members.setdefault(parent, (Entry(parts[i - 1], True), parent + "/"))
        self.readonly = not self._zip or self.encrypted
        if not self.readonly:
            self.label = 'ARCHIVE · ZIP'
        self.children = {}
        for name, (entry, _) in self.members.items():
            parent = name.rpartition("/")[0]
            self.children.setdefault(parent, []).append(entry)

    def _index_extended(self):
        from .archive_runtime import prepare_archive
        prepare_archive()
        try:
            import libarchive
        except (ImportError, OSError) as exc:
            raise RuntimeError('RAR/7z requires libarchive. Support is included in the distributed Mac package.') from exc
        self.children = {}
        with libarchive.file_reader(self.filename, passphrase=self.password) as archive:
            for item in archive:
                raw = item.pathname
                normalized = raw
                while normalized.startswith("./"):
                    normalized = normalized[2:]
                parts = normalized.rstrip("/").split("/")
                if any(p in ("", ".", "..") or "\\" in p or ":" in p or "\0" in p for p in parts):
                    continue
                if not (item.isfile or item.isdir or item.issym or item.islnk):
                    continue
                name = "/".join(parts)
                self.members[name] = (Entry(parts[-1], bool(item.isdir), item.size or 0, item.mtime or 0, bool(item.issym or item.islnk)), raw)
                for i in range(1, len(parts)):
                    parent = "/".join(parts[:i])
                    self.members.setdefault(parent, (Entry(parts[i - 1], True), parent + "/"))
        for name, (entry, _) in self.members.items():
            self.children.setdefault(name.rpartition("/")[0], []).append(entry)

    def _check_unchanged(self):
        info = os.stat(self.filename)
        if (info.st_size, info.st_mtime_ns) != self.signature:
            raise RuntimeError('The archive has changed since it was opened. Reopen it or refresh the panel.')

    def _member_key(self, path):
        key = path.strip('/')
        if key in self.members:
            return key
        # macOS libarchive can return decomposed Unicode names. Preserve the
        # original entries, resolving a pasted canonical spelling only if unique.
        normalized = unicodedata.normalize('NFC', key)
        matches = [name for name in self.members if unicodedata.normalize('NFC', name) == normalized]
        if len(matches) == 1:
            return matches[0]
        raise FileNotFoundError(path)

    @contextlib.contextmanager
    def batch(self):
        if not self.readonly:
            from .zip_edit import transaction
            with transaction(self):
                yield
            return
        if self._extended:
            self._check_unchanged()
            yield
            return
        if getattr(self._local, "archive", None) is not None:
            yield
            return
        self._check_unchanged()
        with self._open() as archive:
            self._local.archive = archive
            try:
                yield
            finally:
                del self._local.archive

    def _open(self):
        if self._zip:
            archive = zipfile.ZipFile(self.filename)
            if self.password:
                archive.setpassword(self.password)
            return archive
        return tarfile.open(self.filename, "r:*")

    def list(self, path: str) -> list[Entry]:
        with self._write_lock:
            return self._list(path)

    def _list(self, path):
        self._check_unchanged()
        prefix = path.strip("/")
        view = getattr(self._local, "zip_view", None)
        if view is not None:
            if prefix and (prefix not in view or not view[prefix][0].is_dir):
                raise NotADirectoryError(path)
            return [e for name, (e, _) in view.items() if name.rpartition("/")[0] == prefix]
        if prefix:
            try:
                prefix = self._member_key(prefix)
            except FileNotFoundError:
                raise NotADirectoryError(path) from None
            if not self.members[prefix][0].is_dir:
                raise NotADirectoryError(path)
        return list(self.children.get(prefix, ()))

    def exists(self, path):
        with self._write_lock:
            view = getattr(self._local, "zip_view", self.members)
            return not path.strip("/") or path.strip("/") in view

    def operation_progress(self, callback):
        if hasattr(self._local, "zip_progress"):
            self._local.zip_progress = callback

    def _require_write(self):
        if self.readonly:
            raise PermissionError('Only local unencrypted ZIP archives are writable.')

    def mkdir(self, path):
        self._require_write()
        from .zip_edit import mkdir
        mkdir(self, path)

    def write_from(self, path, source, progress, overwrite=False):
        self._require_write()
        from .zip_edit import write
        write(self, path, source, progress, overwrite)

    def rename(self, path, destination):
        self._require_write()
        from .zip_edit import rename
        rename(self, path, destination)

    def remove(self, path, entry):
        self._require_write()
        from .zip_edit import remove
        remove(self, path, entry)

    def read_to(self, path: str, output: BinaryIO, progress: Progress) -> None:
        if self._extended:
            import libarchive
            self._check_unchanged()
            entry, raw = self.members[self._member_key(path)]
            if entry.is_link or entry.is_dir:
                raise ValueError('This archive item cannot be read as a file.')
            with libarchive.file_reader(self.filename, passphrase=self.password) as archive:
                for item in archive:
                    if item.pathname == raw:
                        for block in item.get_blocks():
                            output.write(block)
                            progress(len(block))
                        return
            raise FileNotFoundError(path)
        with self.open_reader(path) as stream:
            pump(stream, output, progress)

    @contextlib.contextmanager
    def open_reader(self, path):
        with self._write_lock:
            with self._open_reader(path) as stream:
                yield stream

    @contextlib.contextmanager
    def _open_reader(self, path):
        if self._extended:
            with Provider.open_reader(self, path) as stream:
                yield stream
            return
        self._check_unchanged()
        entry, raw = self.members[self._member_key(path)]
        if entry.is_link:
            raise ValueError('Archive links are not extracted for safety.')
        cached = getattr(self._local, "archive", None)
        with (contextlib.nullcontext(cached) if cached else self._open()) as archive:
            stream = archive.open(raw) if self._zip else archive.extractfile(raw)
            if stream is None:
                raise IsADirectoryError(path)
            with stream:
                yield stream


@dataclass(frozen=True)
class Connection:
    protocol: str
    host: str
    port: int
    username: str
    password: str = field(default="", repr=False)
    keyfile: str = ""
    name: str = ""

    def __post_init__(self):
        from .diagnostic_log import register_secret
        register_secret(self.password)
        if self.protocol not in ("FTP", "FTPS", "SFTP"):
            raise ValueError('Unknown protocol.')
        if not self.host or any(c in self.host for c in "/\r\n\0@"):
            raise ValueError('Enter a server name without protocol or path.')


class RemoteProvider(Provider):
    def __init__(self, connection: Connection):
        self.connection = connection
        self.label = connection.name or f"{connection.protocol} · {connection.host}"
        self._local = local()

    @contextlib.contextmanager
    def batch(self):
        if getattr(self._local, "remote", None) is not None:
            yield
            return
        with self.session() as remote:
            self._local.remote = remote
            try:
                yield
            finally:
                del self._local.remote

    @contextlib.contextmanager
    def session(self):
        cached = getattr(self._local, "remote", None)
        if cached is not None:
            yield cached
            return
        c = self.connection
        logger.info('Connecting · protocol=%s · host=%s · port=%s', c.protocol, c.host, c.port)
        if c.protocol == "SFTP":
            import paramiko
            with paramiko.SSHClient() as client:
                client.load_system_host_keys()
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                client.connect(c.host, port=c.port, username=c.username,
                               password=c.password or None, key_filename=c.keyfile or None,
                               timeout=20, auth_timeout=20, banner_timeout=20)
                with client.open_sftp() as sftp:
                    sftp.get_channel().settimeout(30)
                    yield sftp
        else:
            ftp = (_FTP_TLS(context=ssl.create_default_context(), timeout=30)
                   if c.protocol == "FTPS" else ftplib.FTP(timeout=30))
            try:
                ftp.connect(c.host, c.port)
                ftp.login(c.username or "anonymous", c.password)
                if c.protocol == "FTPS":
                    ftp.prot_p()
                ftp.set_pasv(True)
                yield ftp
            finally:
                ftp.close()

    def list(self, path: str) -> list[Entry]:
        with self.session() as remote:
            if self.connection.protocol == "SFTP":
                return [Entry(item.filename, stat.S_ISDIR(item.st_mode), item.st_size or 0,
                              item.st_mtime or 0, stat.S_ISLNK(item.st_mode), item.st_mode,
                              accessed=item.st_atime or 0, owner=str(item.st_uid) if item.st_uid is not None else "",
                              group=str(item.st_gid) if item.st_gid is not None else "")
                        for item in remote.listdir_attr(path)
                        if item.filename not in (".", "..")]
            result = []
            try:
                items = list(remote.mlsd(path, facts=["type", "size", "modify"]))
            except ftplib.error_perm as exc:
                if not str(exc).startswith(("500", "501", "502", "504", "550")):
                    raise
                from .ftp_listing import parse_listing
                if any(c in path for c in "\r\n\0"):
                    raise ValueError('Invalid FTP path.')
                lines = []
                remote.retrlines("LIST " + path, lines.append)
                return parse_listing(lines)
            for name, facts in items:
                if facts.get("type") in ("cdir", "pdir") or name in (".", ".."):
                    continue
                safe_name(name)
                stamp = facts.get("modify", "").split(".")[0]
                try:
                    modified = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    modified = 0
                kind = facts.get("type", "file")
                result.append(Entry(name, kind == "dir", int(facts.get("size", 0)), modified,
                                    "slink" in kind.lower()))
            return result

    def read_to(self, path: str, output: BinaryIO, progress: Progress) -> None:
        with self.session() as remote:
            if self.connection.protocol == "SFTP":
                with remote.open(path, "rb") as stream:
                    pump(_SFTPChunkReader(stream, remote.stat(path).st_size), output, progress)
            else:
                def receive(block):
                    output.write(block)
                    progress(len(block))
                try:
                    remote.retrbinary("RETR " + path, receive, blocksize=256 * 1024)
                except BaseException:
                    remote.close()
                    self._local.remote = None
                    raise

    def read_range(self, path, output, progress, offset=0):
        with self.session() as remote:
            try:
                if self.connection.protocol == "SFTP":
                    with remote.open(path, "rb") as stream:
                        stream.seek(offset)
                        pump(stream, output, progress)
                else:
                    def receive(block):
                        output.write(block)
                        progress(len(block))
                    remote.retrbinary("RETR " + path, receive, blocksize=256 * 1024, rest=offset or None)
            except BaseException:
                self._abort_ftp(remote)
                remote.close()
                self._local.remote = None
                raise

    def append_range(self, path, source, progress, offset=0):
        with self.session() as remote:
            try:
                if self.connection.protocol == "SFTP":
                    with remote.open(path, "r+b" if offset else "wb") as output:
                        output.seek(offset)
                        pump(source, output, progress)
                else:
                    remote.storbinary("STOR " + path, source, blocksize=256 * 1024,
                                      callback=lambda block: progress(len(block)), rest=offset or None)
            except BaseException:
                self._abort_ftp(remote)
                remote.close()
                self._local.remote = None
                raise

    def _abort_ftp(self, remote):
        if self.connection.protocol == 'SFTP' or getattr(remote, 'sock', None) is None:
            return
        # In-band ABOR also works over TLS (FTP.abort uses unsupported OOB).
        # Wait for the server to release the interrupted data transfer's file.
        with contextlib.suppress(*ftplib.all_errors):
            remote.sock.settimeout(3)
            remote.putcmd('ABOR')
            for _ in range(3):
                reply = remote.getmultiline()
                if reply.startswith(('225', '226')):
                    break
                if not reply.startswith('426'):
                    break

    @contextlib.contextmanager
    def open_reader(self, path):
        if self.connection.protocol == "SFTP":
            with self.session() as remote:
                with remote.open(path, "rb") as stream:
                    yield _SFTPChunkReader(stream, remote.stat(path).st_size)
        else:
            with super().open_reader(path) as stream:
                yield stream

    def write_from(self, path: str, source: BinaryIO, progress: Progress, overwrite=False) -> None:
        temporary = path + ".stereo-" + uuid.uuid4().hex + ".part"
        with self.session() as remote:
            try:
                if self.connection.protocol == "SFTP":
                    with remote.open(temporary, "wb") as output:
                        output.set_pipelined(True)
                        pump(source, output, progress)
                    if overwrite:
                        remote.posix_rename(temporary, path)
                    else:
                        remote.rename(temporary, path)
                else:
                    remote.storbinary("STOR " + temporary, source, blocksize=256 * 1024,
                                      callback=lambda block: progress(len(block)))
                    try:
                        remote.rename(temporary, path)
                    except ftplib.error_perm:
                        if not overwrite:
                            raise
                        # Some FTP servers refuse RNTO when the destination exists.
                        # Keep the original until the complete upload is published.
                        backup = path + '.stereo-backup-' + uuid.uuid4().hex
                        remote.rename(path, backup)
                        try:
                            remote.rename(temporary, path)
                        except BaseException as exc:
                            try:
                                remote.rename(backup, path)
                            except Exception:
                                raise IOError(f'Upload could not be published or restored. The original file is retained at {backup}.') from exc
                            raise
                        try:
                            remote.delete(backup)
                        except Exception:
                            logger.warning('FTP upload completed; previous file retained at %s', backup)
            except BaseException:
                # A canceled FTP data transfer leaves unread replies on the control
                # channel. Clean up using a fresh session, never that poisoned one.
                self._abort_ftp(remote)
                remote.close()
                self._local.remote = None
                with contextlib.suppress(Exception):
                    with self.session() as cleanup:
                        (cleanup.remove if self.connection.protocol == "SFTP" else cleanup.delete)(temporary)
                raise

    def mkdir(self, path: str) -> None:
        with self.session() as remote:
            (remote.mkdir if self.connection.protocol == "SFTP" else remote.mkd)(path)

    def rename(self, path: str, destination: str) -> None:
        if self.exists(destination):
            raise FileExistsError(destination)
        with self.session() as remote:
            remote.rename(path, destination)

    def remove(self, path: str, entry: Entry) -> None:
        if entry.is_dir and not entry.is_link:
            for child in self.list(path):
                self.remove(self.join(path, child.name), child)
        with self.session() as remote:
            if entry.is_dir and not entry.is_link:
                (remote.rmdir if self.connection.protocol == "SFTP" else remote.rmd)(path)
            else:
                (remote.remove if self.connection.protocol == "SFTP" else remote.delete)(path)
