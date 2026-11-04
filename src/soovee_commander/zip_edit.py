"""One atomic ZIP rewrite per batch, with staged incoming files and no full extraction."""
import contextlib
from dataclasses import replace
from datetime import datetime
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from .providers import Entry, LocalProvider


@contextlib.contextmanager
def transaction(provider):
    with provider._write_lock:
        with _transaction(provider) as view:
            yield view


@contextlib.contextmanager
def _transaction(provider):
    active = getattr(provider._local, "zip_view", None)
    if active is not None:
        yield active
        return
    provider._check_unchanged()
    view = dict(provider.members)
    staged = []
    provider._local.zip_view = view
    provider._local.zip_staged = staged
    provider._local.zip_dirty = False
    provider._local.zip_progress = lambda count: None
    cached = provider._open()
    provider._local.archive = cached
    dirty = False
    try:
        yield view
        cached.close()
        del provider._local.archive
        dirty = provider._local.zip_dirty
        if dirty:
            provider._check_unchanged()
            progress = provider._local.zip_progress
            def produce(output):
                with zipfile.ZipFile(provider.filename) as original, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as target:
                    target.comment = original.comment
                    for name, (entry, raw) in view.items():
                        progress(0)
                        if entry.is_dir:
                            target.writestr(name.rstrip("/") + "/", b"")
                            continue
                        if isinstance(raw, Path):
                            info = zipfile.ZipInfo.from_file(raw, arcname=name, strict_timestamps=False)
                            info.compress_type = zipfile.ZIP_DEFLATED
                            source = raw.open("rb")
                        else:
                            info = original.getinfo(raw)
                            import copy
                            info = copy.copy(info)
                            info.filename = name
                            source = original.open(raw)
                        with source, target.open(info, "w", force_zip64=True) as member:
                            while block := source.read(256 * 1024):
                                progress(0)
                                member.write(block)
                provider._check_unchanged()
                progress(0)
            LocalProvider().write_with(provider.filename, produce, progress, metadata_path=provider.filename, overwrite=True)
    finally:
        cached.close()
        if hasattr(provider._local, "archive"):
            del provider._local.archive
        for path in staged:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        del provider._local.zip_view
        del provider._local.zip_staged
        del provider._local.zip_dirty
        del provider._local.zip_progress
    if dirty:
        fresh = type(provider)(provider.filename, provider.password)
        # Keep per-thread contexts and the lock alive for concurrent readers.
        for attribute in ("signature", "members", "children", "encrypted", "readonly", "label"):
            setattr(provider, attribute, getattr(fresh, attribute))


def mkdir(provider, path):
    name = path.strip("/")
    with transaction(provider) as view:
        if name in view:
            raise FileExistsError(path)
        view[name] = (Entry(name.rsplit("/", 1)[-1], True), name + "/")
        provider._local.zip_dirty = True


def write(provider, path, source, progress, overwrite=False):
    name = path.strip("/")
    with transaction(provider) as view:
        if name in view and (not overwrite or view[name][0].is_dir):
            raise FileExistsError(path)
        fd, temporary = tempfile.mkstemp(prefix="stereo-zip-entry-")
        staged = Path(temporary)
        provider._local.zip_staged.append(staged)
        size = 0
        with os.fdopen(fd, "wb") as output:
            while block := source.read(256 * 1024):
                output.write(block)
                size += len(block)
                progress(len(block))
        view[name] = (Entry(name.rsplit("/", 1)[-1], False, size, staged.stat().st_mtime), staged)
        provider._local.zip_dirty = True
        provider._local.zip_progress = progress


def remove(provider, path, entry):
    prefix = path.strip("/")
    with transaction(provider) as view:
        if prefix not in view:
            raise FileNotFoundError(path)
        for name in list(view):
            if name == prefix or name.startswith(prefix + "/"):
                del view[name]
        provider._local.zip_dirty = True


def rename(provider, path, destination):
    old, new = path.strip("/"), destination.strip("/")
    with transaction(provider) as view:
        if old not in view:
            raise FileNotFoundError(path)
        if new in view or new.startswith(old + "/"):
            raise FileExistsError(destination)
        for name in list(view):
            if name == old or name.startswith(old + "/"):
                entry, raw = view.pop(name)
                updated = new + name[len(old):]
                view[updated] = (replace(entry, name=updated.rsplit("/", 1)[-1]), raw)
        provider._local.zip_dirty = True
