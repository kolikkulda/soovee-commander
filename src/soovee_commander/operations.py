"""Cancelable transfers shared by the UI and tests."""
from __future__ import annotations

import io
import os
import re
import shutil
from contextlib import ExitStack
from pathlib import Path
import tempfile
import zipfile
from datetime import datetime
from threading import Event

from .providers import ArchiveProvider, Entry, LocalProvider, Provider, RemoteProvider, copy_metadata
from .nativefs import rename_no_replace
from .transfer_status import emit as transfer_event


class Cancelled(Exception):
    pass


def copy_entries(source: Provider, source_path: str, destination: Provider,
                 destination_path: str, entries: list[Entry], cancel: Event,
                 report=lambda message, count: None, conflict="error", resume=False) -> int:
    if isinstance(source, ArchiveProvider) and isinstance(destination, ArchiveProvider) and source.filename == destination.filename:
        raise ValueError('Copying within the same archive is not supported. Rename the item or use another archive.')
    if isinstance(source, LocalProvider) and isinstance(destination, ArchiveProvider):
        archive_path = Path(destination.filename).resolve()
        for entry in entries:
            original = Path(source.join(source_path, entry.name)).resolve()
            if original == archive_path or (entry.is_dir and original in archive_path.parents):
                raise ValueError('An archive cannot be packed into itself.')
    if destination.readonly:
        raise PermissionError('This archive does not support writing.')
    if isinstance(source, LocalProvider) and isinstance(destination, LocalProvider):
        target = Path(destination_path).resolve()
        for entry in entries:
            original = Path(source.join(source_path, entry.name)).resolve()
            final = target / entry.name
            # Into its own folder is fine when the copy gets a new name ("name (2)").
            if (final == original and conflict != "rename") or (entry.is_dir and original in final.parents):
                raise ValueError('Cannot copy a folder into itself or a subfolder.')
    if isinstance(destination, LocalProvider) and hasattr(os, 'statvfs'):
        info = os.statvfs(destination_path)
        if info.f_flag & getattr(os, 'ST_RDONLY', 1):
            raise PermissionError(f'Destination filesystem is read only: {destination_path}. For FTP, connect directly using an ftp:// address instead of a Finder-mounted volume.')
    if conflict not in ("error", "skip", "rename", "overwrite"):
        raise ValueError('Unknown conflict strategy.')
    total = 0
    cache_destination = isinstance(destination, RemoteProvider) or getattr(destination, "cache_listings", False)
    remote_directories = {}
    source_directories = {}

    def target_directory(path):
        if path not in remote_directories:
            remote_directories[path] = {e.name: e for e in destination.list(path)}
        return remote_directories[path]

    def target_exists(path):
        if cache_destination:
            return os.path.basename(path) in target_directory(destination.parent(path))
        return destination.exists(path)

    def check():
        if cancel.is_set():
            raise Cancelled('Transfer canceled. Completed files remain at the destination.')

    def copy_one(src_path: str, dst_path: str, entry: Entry):
        nonlocal total
        check()
        if entry.is_link:
            raise ValueError(f'Copying symbolic links is not supported: {entry.name}')
        exists = target_exists(dst_path)
        if exists:
            if resume and not entry.is_dir:
                from .advanced import digest
                if not isinstance(destination, (LocalProvider, RemoteProvider)):
                    raise ValueError('This destination does not support resume.')
                target_entry = next(e for e in destination.list(destination.parent(dst_path)) if e.name == os.path.basename(dst_path))
                if target_entry.is_dir or target_entry.is_link or target_entry.size != entry.size or digest(source, src_path, cancel) != digest(destination, dst_path, cancel):
                    raise FileExistsError(f'The completed destination has different contents: {dst_path}')
                report(f'Already complete · {entry.name}', 0)
                transfer_event(report, 'skip', path=dst_path, size=entry.size)
                return
            if conflict == "skip":
                report(f'Skipped · {entry.name}', 0)
                skipped_size = entry.size if not entry.is_dir else planned_size(src_path, entry)
                transfer_event(report, 'skip', path=dst_path, size=skipped_size, files=planned_count(src_path, entry))
                return
            if conflict == "rename":
                parent = destination.parent(dst_path)
                stem, suffix = (entry.name, "") if entry.is_dir else (Path(entry.name).stem, Path(entry.name).suffix)
                if not stem:   # ".bashrc" has no suffix of its own
                    stem, suffix = entry.name, ""
                numbered = re.fullmatch(r"(.*) \((\d+)\)", stem)
                # Copying "Report (2)" again continues with "Report (3)", not "Report (2) (2)".
                stem, number = (numbered.group(1), int(numbered.group(2)) + 1) if numbered else (stem, 2)
                while exists:
                    alternate = f"{stem} ({number}){suffix}"
                    dst_path = destination.join(parent, alternate)
                    exists = target_exists(dst_path)
                    number += 1
            elif conflict != "overwrite" and not (resume and entry.is_dir):
                raise FileExistsError(f'The destination already exists: {dst_path}. Choose skip, rename or replace.')
        if entry.is_dir:
            if exists:
                existing = (target_directory(destination.parent(dst_path))[os.path.basename(dst_path)]
                            if cache_destination else
                            next(e for e in destination.list(destination.parent(dst_path))
                                 if e.name == os.path.basename(dst_path)))
                if not existing.is_dir or existing.is_link:
                    raise FileExistsError(f'The destination item is not a regular folder: {dst_path}')
            else:
                destination.mkdir(dst_path)
                if cache_destination:
                    remote_directories[dst_path] = {}
            for child in source_directories[src_path]:
                copy_one(source.join(src_path, child.name), destination.join(dst_path, child.name), child)
            if isinstance(source, LocalProvider) and isinstance(destination, LocalProvider):
                copy_metadata(src_path, dst_path)
        else:
            transferred_file = 0
            transfer_event(report, 'file', source=src_path, destination=dst_path, size=entry.size)
            if isinstance(source, LocalProvider):
                info = os.stat(src_path)
                if info.st_size != entry.size or info.st_mtime != entry.modified:
                    raise IOError('The source file changed since it was listed. Refresh the source and try again.')
            def downloading(count):
                check()
                report(f'Reading · {entry.name}', count)

            def uploading(count):
                nonlocal total, transferred_file
                check()
                total += count
                transferred_file += count
                transfer_event(report, "advance", bytes=transferred_file)
                report(f'Writing · {entry.name}', count)

            if resume and ((isinstance(source, RemoteProvider) and isinstance(destination, LocalProvider)) or
                           (isinstance(source, LocalProvider) and isinstance(destination, RemoteProvider))):
                if exists:
                    raise FileExistsError('Resume does not overwrite completed files.')
                from .resume import transfer
                def resume_report(message, count):
                    nonlocal transferred_file, total
                    # Resume reports network bytes; final publication is a separate phase.
                    transferred_file += count
                    total += count
                    transfer_event(report, 'advance', bytes=transferred_file)
                    report(message, count)
                transfer(source, src_path, destination, dst_path, cancel, resume_report)
            elif isinstance(destination, LocalProvider):
                destination.write_with(
                    dst_path, lambda output: source.read_to(src_path, output, uploading), uploading,
                    metadata_path=src_path if isinstance(source, LocalProvider) else None,
                    modified=entry.modified, overwrite=exists)
            elif isinstance(source, RemoteProvider) and source.connection.protocol != "SFTP":
                # Two FTP data channels cannot share a control connection. This
                # less common server-to-server case stages only the current file.
                with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as buffer:
                    source.read_to(src_path, buffer, downloading)
                    check()
                    buffer.seek(0)
                    destination.write_from(dst_path, buffer, uploading, overwrite=exists)
            else:
                with source.open_reader(src_path) as stream:
                    destination.write_from(dst_path, stream, uploading, overwrite=exists)
        if not entry.is_dir:
            transfer_event(report, "file_done", path=dst_path, size=entry.size, transferred=transferred_file)
        if cache_destination:
            target_directory(destination.parent(dst_path))[os.path.basename(dst_path)] = entry

    def planned_count(path, entry):
        return sum(planned_count(source.join(path, e.name), e) for e in source_directories[path]) if entry.is_dir else 1

    def planned_size(path, entry):
        if not entry.is_dir:
            return entry.size
        return sum(planned_size(source.join(path, e.name), e) for e in source_directories[path])

    check()
    with ExitStack() as stack:
        stack.enter_context(source.batch())
        if destination is not source:
            stack.enter_context(destination.batch())
        todo = [(source.join(source_path, e.name), e) for e in entries]
        planned_bytes = planned_files = 0
        while todo:
            check()
            path, item = todo.pop()
            if item.is_link:
                raise ValueError(f'Copying symbolic links is not supported: {item.name}')
            if item.is_dir:
                transfer_event(report, 'scan', path=path)
                children = source.list(path)
                source_directories[path] = children
                todo.extend((source.join(path, child.name), child) for child in children)
            else:
                planned_bytes += item.size
                planned_files += 1
        transfer_event(report, 'plan', bytes=planned_bytes, files=planned_files)
        for entry in entries:
            copy_one(source.join(source_path, entry.name), destination.join(destination_path, entry.name), entry)
    return total


def move_local(source: LocalProvider, source_path: str, destination: LocalProvider,
               destination_path: str, entries: list[Entry], cancel: Event, report) -> int:
    # Delete each source only after that entire selected item copied successfully.
    total = 0
    transfer_event(report, "plan", bytes=0, files=len(entries))
    for entry in entries:
        if cancel.is_set():
            raise Cancelled('Move canceled.')
        original = source.join(source_path, entry.name)
        target = destination.join(destination_path, entry.name)
        resolved, final = Path(original).resolve(), Path(target).resolve()
        if resolved == final or (entry.is_dir and resolved in final.parents):
            raise ValueError('Cannot move a folder into itself or a subfolder.')
        if rename_no_replace(original, target):
            transfer_event(report, 'file', source=original, destination=target, size=0)
            transfer_event(report, 'file_done', path=target, size=0)
            report(f'Moving · {entry.name}', 0)
            continue
        snapshot = _source_snapshot(original)
        total += copy_entries(source, source_path, destination, destination_path, [entry], cancel, report)
        if cancel.is_set():
            raise Cancelled('Copy complete; the source was kept.')
        if snapshot != _source_snapshot(original):
            raise IOError('The source changed during the move. Both source and copy were kept.')
        source.remove(original, entry)
    return total


def _source_snapshot(path):
    def signature(name):
        info = os.lstat(name)
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode

    snapshot = {"": signature(path)}
    if os.path.isdir(path) and not os.path.islink(path):
        for directory, folders, files in os.walk(path, followlinks=False):
            for name in folders + files:
                item = os.path.join(directory, name)
                snapshot[os.path.relpath(item, path)] = signature(item)
    return snapshot


def create_zip(source: Provider, source_path: str, destination_path: str,
               entries: list[Entry], cancel: Event, report=lambda message, count: None):
    """Stream selected files into a new ZIP; publish only after its directory is complete."""
    target = Path(destination_path).resolve()
    if isinstance(source, LocalProvider):
        for entry in entries:
            original = Path(source.join(source_path, entry.name)).resolve()
            if original == target or (entry.is_dir and original in target.parents):
                raise ValueError('A ZIP cannot be created inside the folder being packed.')

    def check():
        if cancel.is_set():
            raise Cancelled('Archive creation canceled.')

    def produce(output):
        with source.batch(), zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            def add(base, name, entry):
                check()
                if entry.is_link:
                    raise ValueError(f'Archiving symbolic links is not supported: {entry.name}')
                path = source.join(base, entry.name)
                if isinstance(source, LocalProvider):
                    info = zipfile.ZipInfo.from_file(path, arcname=name, strict_timestamps=False)
                else:
                    stamp = datetime.fromtimestamp(entry.modified) if entry.modified else datetime(1980, 1, 1)
                    date = (max(1980, min(stamp.year, 2107)), stamp.month, stamp.day,
                            stamp.hour, stamp.minute, stamp.second)
                    info = zipfile.ZipInfo(name + ("/" if entry.is_dir else ""), date_time=date)
                info.compress_type = zipfile.ZIP_DEFLATED
                if entry.is_dir:
                    archive.writestr(info, b"")
                    for child in source.list(path):
                        add(path, name + "/" + child.name, child)
                else:
                    with archive.open(info, "w", force_zip64=True) as member:
                        def progress(count):
                            check()
                            report(f'Packing · {entry.name}', count)
                        source.read_to(path, member, progress)
            for entry in entries:
                add(source_path, entry.name, entry)
        check()

    LocalProvider().write_with(destination_path, produce, lambda count: check())


class _PreviewFull(Exception):
    pass


def preview(provider: Provider, path: str, limit: int = 1024 * 1024) -> bytes:
    class BoundedBuffer(io.BytesIO):
        def write(self, data):
            remaining = limit - self.tell()
            super().write(data[:remaining])
            if len(data) > remaining:
                raise _PreviewFull()
            return len(data)

    output = BoundedBuffer()
    try:
        provider.read_to(path, output, lambda count: None)
    except _PreviewFull:
        pass
    return output.getvalue()
