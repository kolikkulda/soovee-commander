"""Persistent resumable downloads/uploads. Partial data is never the final name."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .providers import LocalProvider, RemoteProvider
from .operations import Cancelled


def identity(provider, path):
    if isinstance(provider, LocalProvider):
        info = os.stat(path, follow_symlinks=False)
        return ["local", os.path.abspath(path), info.st_size, info.st_mtime_ns]
    entry = next(e for e in provider.list(provider.parent(path)) if e.name == path.rsplit("/", 1)[-1])
    c = provider.connection
    return [c.protocol, c.host, c.port, c.username, path, entry.size, entry.modified]


def transfer(source, src, destination, dst, cancel, report=lambda *args: None):
    if not ((isinstance(source, RemoteProvider) and isinstance(destination, LocalProvider)) or
            (isinstance(source, LocalProvider) and isinstance(destination, RemoteProvider))):
        raise ValueError('Resume is available between local disk and FTP/FTPS/SFTP.')
    if destination.exists(dst):
        raise FileExistsError('The destination already exists; resume does not overwrite completed files.')
    descriptor = identity(source, src)
    key = hashlib.sha256(json.dumps([descriptor[:-2], str(dst), getattr(getattr(destination, 'connection', None), 'host', ''), getattr(getattr(destination, 'connection', None), 'username', '')]).encode()).hexdigest()[:32]
    def check():
        if cancel.is_set():
            raise Cancelled('Transfer paused; partial data is kept for resuming.')
    # Cross-process lock: QLockFile handles stale process locks, also on Windows.
    from PySide6.QtCore import QLockFile
    lock = QLockFile(str(Path(tempfile.gettempdir()) / ("stereo-resume-" + key + ".lock")))
    if not lock.tryLock(0):
        raise RuntimeError('The same resumed transfer is already running.')
    try:
        if isinstance(destination, LocalProvider):
            partial = Path(dst).parent / (".stereo-resume-" + key + ".part")
            state = partial.with_suffix(".json")
            if partial.is_symlink() or state.is_symlink():
                raise ValueError('A partial transfer must not be a symbolic link.')
            def partial_hash():
                result = hashlib.sha256()
                with partial.open("rb") as stream:
                    while block := stream.read(256 * 1024):
                        check()
                        result.update(block)
                return result.hexdigest()
            if partial.exists():
                saved = json.loads(state.read_text(encoding='utf-8'))
                if saved.get("sha256") and partial_hash() != saved["sha256"]:
                    raise RuntimeError('The partial file has changed since interruption; it will not be used.')
                if saved.get("source") != descriptor:
                    raise RuntimeError(f'The source changed. Remove the old partial transfer {partial.name} and its matching .json file.')
            else:
                partial.touch(exist_ok=False)
                state.write_text(json.dumps({"source": descriptor}))
            offset = partial.stat().st_size
            if offset > descriptor[-2]:
                raise ValueError('The partial file is larger than the source.')
            check()
            from .transfer_status import emit
            emit(report, "resume", offset=offset)
            report(f'Resuming from {offset} B · {src}', 0)
            try:
                with partial.open("ab") as output:
                    source.read_range(src, output, lambda count: (check(), report(src, count)), offset)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                # Store a checkpoint even on cancellation. Hashing local bytes is
                # bounded and does not require a live network connection.
                result = hashlib.sha256()
                with partial.open("rb") as stream:
                    while block := stream.read(256 * 1024):
                        result.update(block)
                state.write_text(json.dumps({"source": descriptor, "sha256": result.hexdigest()}))
            check()
            if identity(source, src) != descriptor or partial.stat().st_size != descriptor[-2]:
                raise RuntimeError('The source changed or the transfer is incomplete; no final file was published.')
            if descriptor[-1]:
                os.utime(partial, (descriptor[-1], descriptor[-1]))
            # Reuse atomic publication and metadata handling of LocalProvider.
            with partial.open("rb") as stream:
                destination.write_from(dst, stream, lambda count: check())
            partial.unlink()
            state.unlink()
        else:
            from .advanced import digest
            # Content hash binds the remote staging name to immutable local bytes.
            original_hash = digest(source, src, cancel)
            partial = destination.join(destination.parent(dst), ".stereo-resume-" + key + "-" + original_hash.hex()[:16] + ".part")
            entries = {e.name: e for e in destination.list(destination.parent(dst))}
            found = entries.get(partial.rsplit("/", 1)[-1])
            if found and (found.is_dir or found.is_link):
                raise ValueError('The partial transfer is not a regular file.')
            offset = found.size if found else 0
            if offset > descriptor[-2]:
                raise ValueError('The remote partial transfer is larger than the source.')
            if offset:
                # Verify the entire existing remote prefix before appending.
                remote_hash = digest(destination, partial, cancel)
                local_hash = hashlib.sha256()
                with open(src, "rb") as stream:
                    remaining = offset
                    while remaining:
                        check()
                        block = stream.read(min(256 * 1024, remaining))
                        if not block:
                            raise IOError('The source was truncated.')
                        remaining -= len(block)
                        local_hash.update(block)
                if remote_hash != local_hash.digest():
                    raise RuntimeError('Remote partial data does not match the source. The transfer was not modified.')
            from .transfer_status import emit
            emit(report, "resume", offset=offset)
            report(f'Resuming from {offset} B · {src}', 0)
            with open(src, "rb") as stream:
                stream.seek(offset)
                destination.append_range(partial, stream, lambda count: (check(), report(src, count)), offset)
            check()
            if identity(source, src) != descriptor or digest(source, src, cancel) != original_hash or digest(destination, partial, cancel) != original_hash:
                raise RuntimeError('Resume verification failed; the source and partial data were kept.')
            destination.rename(partial, dst)
    finally:
        lock.unlock()
