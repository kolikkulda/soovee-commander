"""Cancelable file tools. Workers never access widgets and never follow directory links."""
from dataclasses import dataclass
import fnmatch
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
from threading import Event
import uuid

from .operations import Cancelled, copy_entries, move_local
from .providers import LocalProvider, RemoteProvider, safe_name


def check(cancel):
    if cancel.is_set():
        raise Cancelled('The operation was canceled.')


def walk(provider, root, cancel, report=lambda *args: None, *, fresh_metadata=False):
    pending = [(root, "")]
    while pending:
        base, relative = pending.pop()
        check(cancel)
        report(f'Scanning · {base}', 0)
        entries = provider.list(base, fresh=fresh_metadata) if isinstance(provider, LocalProvider) else provider.list(base)
        for entry in entries:
            check(cancel)
            path = provider.join(base, entry.name)
            name = relative + entry.name
            yield name, path, entry
            if entry.is_dir and not entry.is_link:
                pending.append((path, name + "/"))


def folder_size(provider, root, cancel, report=lambda *args: None):
    size = files = folders = 0
    with provider.batch():
        for _, _, entry in walk(provider, root, cancel, report):
            if entry.is_link:
                continue
            if entry.is_dir:
                folders += 1
            else:
                files += 1
                size += entry.size
    return size, files, folders


def contains(provider, path, needle, cancel):
    """Streaming exact byte search; only needle + one chunk kept in RAM."""
    class Found(Exception):
        pass
    class Sink:
        tail = b""
        def write(self, data):
            check(cancel)
            combined = self.tail + data
            if needle in combined:
                raise Found
            self.tail = combined[-max(0, len(needle) - 1):] if len(needle) > 1 else b""
            return len(data)
    try:
        provider.read_to(path, Sink(), lambda count: check(cancel))
    except Found:
        return True
    return False


def search(provider, root, pattern, text, cancel, report=lambda *args: None, limit=100_000, *, modified_after=None, modified_before=None, min_size=None, max_size=None, kind="all"):
    masks = [s.strip().casefold() for s in pattern.split(";") if s.strip()] or ["*"]
    needle = text.encode("utf-8")
    if len(needle) > 65536:
        raise ValueError('The search text may be at most 64 KB.')
    results, errors = [], []
    # Unreadable content is reported; an unreadable directory aborts rather than
    # returning an apparently complete result.
    with provider.batch():
        for relative, path, entry in walk(provider, root, cancel, report):
            if not any(fnmatch.fnmatchcase(entry.name.casefold(), mask) for mask in masks):
                continue
            if kind == "files" and entry.is_dir or kind == "folders" and not entry.is_dir:
                continue
            if modified_after is not None and entry.modified < modified_after:
                continue
            if modified_before is not None and entry.modified > modified_before:
                continue
            if min_size is not None and (entry.is_dir or entry.size < min_size):
                continue
            if max_size is not None and (entry.is_dir or entry.size > max_size):
                continue
            if needle:
                if entry.is_dir or entry.is_link:
                    continue
                try:
                    if not contains(provider, path, needle, cancel):
                        continue
                except Cancelled:
                    raise
                except Exception as exc:
                    errors.append(f"{relative}: {exc}")
                    continue
            results.append((relative, path, entry))
            if len(results) >= limit:
                raise ValueError(f'More than {limit}. Narrow your search.')
    return results, errors


def digest(provider, path, cancel):
    result = hashlib.sha256()
    class Sink:
        def write(self, data):
            check(cancel)
            result.update(data)
            return len(data)
    provider.read_to(path, Sink(), lambda count: check(cancel))
    return result.digest()


def signature(entry):
    return (entry.is_dir, entry.size, entry.modified, entry.is_link) if entry else None


@dataclass(frozen=True)
class Difference:
    name: str
    left: object
    right: object
    status: str
    left_hash: bytes | None = None
    right_hash: bytes | None = None


def compare(left, lp, right, rp, cancel, by_content=True, report=lambda *args: None):
    with left.batch(), right.batch():
        a = {name: (path, entry) for name, path, entry in walk(left, lp, cancel, report, fresh_metadata=True)}
        b = {name: (path, entry) for name, path, entry in walk(right, rp, cancel, report, fresh_metadata=True)}
        result = []
        for name in sorted(a.keys() | b.keys(), key=str.casefold):
            check(cancel)
            x, y = a.get(name), b.get(name)
            hx = digest(left, x[0], cancel) if by_content and x and not x[1].is_dir and not x[1].is_link else None
            hy = digest(right, y[0], cancel) if by_content and y and not y[1].is_dir and not y[1].is_link else None
            if not x:
                status = 'Right only'
            elif not y:
                status = 'Left only'
            elif x[1].is_link or y[1].is_link:
                status = 'Link — skip'
            elif x[1].is_dir != y[1].is_dir:
                status = 'Type conflict'
            elif x[1].is_dir:
                status = 'Equal'
            elif x[1].size != y[1].size:
                status = 'Different'
            elif by_content:
                report(f'Comparing contents · {name}', 0)
                status = 'Equal' if hx == hy else 'Different'
            else:
                status = 'Equal' if abs(x[1].modified - y[1].modified) < 1 else 'Different'
            result.append(Difference(name, x[1] if x else None, y[1] if y else None, status, hx, hy))
        for provider, root, before in ((left, lp, a), (right, rp, b)):
            after = {name: signature(entry) for name, _, entry in walk(provider, root, cancel, report, fresh_metadata=True)}
            if after != {name: signature(item[1]) for name, item in before.items()}:
                raise RuntimeError('The folder changed during comparison. Compare again.')
        return result


def relative_path(provider, base, relative):
    for name in relative.split("/"):
        base = provider.join(base, name)
    return base


def sync_entries(source, src, destination, dst, differences, cancel, report=lambda *args: None, direction="right"):
    """Apply an explicitly reviewed one-way plan. Never deletes extra targets."""
    # Snapshot full trees including content before touching either side. Do not
    # silently overwrite files modified since Compare.
    if isinstance(source, LocalProvider) and isinstance(destination, LocalProvider):
        a, b = Path(src).resolve(), Path(dst).resolve()
        if a == b or a in b.parents or b in a.parents:
            raise ValueError('Synchronized folders must not overlap.')
    with source.batch(), destination.batch():
        destination.operation_progress(lambda count: check(cancel))
        inventories = [{name: entry for name, _, entry in walk(provider, root, cancel, report, fresh_metadata=True)} for provider, root in ((source, src), (destination, dst))]
        for diff in differences:
            entry, target = (diff.left, diff.right) if direction == "right" else (diff.right, diff.left)
            if (entry and entry.is_link) or (target and target.is_link) or (entry and target and entry.is_dir != target.is_dir):
                raise ValueError(f'Resolve the link or type conflict first: {diff.name}')
            check(cancel)
            expected_src, expected_dst = (diff.left, diff.right) if direction == "right" else (diff.right, diff.left)
            hashes = (diff.left_hash, diff.right_hash) if direction == "right" else (diff.right_hash, diff.left_hash)
            for provider, root, expected, expected_hash, inventory in ((source, src, expected_src, hashes[0], inventories[0]), (destination, dst, expected_dst, hashes[1], inventories[1])):
                path = relative_path(provider, root, diff.name)
                actual = inventory.get(diff.name)
                if signature(actual) != signature(expected):
                    raise RuntimeError(f'Item changed since comparison: {diff.name}. Compare again.')
                if expected_hash is not None and digest(provider, path, cancel) != expected_hash:
                    raise RuntimeError(f'Contents changed since comparison: {diff.name}. Compare again.')
        for diff in sorted(differences, key=lambda d: (d.name.count("/"), d.name.casefold())):
            check(cancel)
            entry, target = (diff.left, diff.right) if direction == "right" else (diff.right, diff.left)
            if entry is None or diff.status == 'Equal':
                continue
            if entry.is_link or (target and (target.is_link or target.is_dir != entry.is_dir)):
                raise ValueError(f"Cannot synchronize a link or type conflict: {diff.name}")
            path = relative_path(destination, dst, diff.name)
            if entry.is_dir:
                if target is None:
                    destination.mkdir(path)
                continue
            source_path = relative_path(source, src, diff.name)
            copy_entries(source, source.parent(source_path), destination, destination.parent(path), [entry], cancel, report, conflict="overwrite" if target else "error")


def rename_names(entries, mask="[N]", extension="[E]", find="", replacement="", case="keep", start=1, digits=1, **options):
    from .rename_masks import build_names
    return build_names(entries, mask, extension, find, replacement, case, start, digits, **options)


def multi_rename(provider, base, entries, names, cancel, report=lambda *args: None):
    if provider.readonly or len(entries) != len(names):
        raise ValueError('Invalid rename plan.')
    for name in names:
        safe_name(name)
    if len({n.casefold() for n in names}) != len(names):
        raise ValueError('Duplicate destination names.')
    with provider.batch():
        provider.operation_progress(lambda count: check(cancel))
        existing = {e.name: e for e in provider.list(base)}
        originals = {entry.name for entry in entries}
        for entry, name in zip(entries, names):
            if signature(existing.get(entry.name)) != signature(entry):
                raise RuntimeError(f'The source changed: {entry.name}')
            if any(n.casefold() == name.casefold() and n not in originals for n in existing):
                raise FileExistsError(name)
        staged, completed = [], []
        try:
            for entry, name in zip(entries, names):
                check(cancel)
                if entry.name == name:
                    continue
                temp = ".stereo-rename-" + uuid.uuid4().hex
                provider.rename(provider.join(base, entry.name), provider.join(base, temp))
                staged.append((entry.name, temp, name))
            for old, temp, name in staged:
                check(cancel)
                provider.rename(provider.join(base, temp), provider.join(base, name))
                completed.append((old, temp, name))
                report(f'Renamed · {old} → {name}', 0)
        except Exception as exc:
            failures = []
            # Put all completed destinations back into their unique staging names
            # before restoring originals (supports cycles like a→b, b→a).
            for old, temp, name in reversed(completed):
                try:
                    provider.rename(provider.join(base, name), provider.join(base, temp))
                except Exception as rollback:
                    failures.append(f"{name}: {rollback}")
            for old, temp, name in reversed(staged):
                try:
                    provider.rename(provider.join(base, temp), provider.join(base, old))
                except Exception as rollback:
                    failures.append(f"{temp} → {old}: {rollback}")
            if failures:
                raise RuntimeError(f'{exc}\nRollback was incomplete:\n' + "\n".join(failures)) from exc
            raise
    return list(zip(names, [e.name for e in entries]))


def same_server(a, b):
    return isinstance(a, RemoteProvider) and isinstance(b, RemoteProvider) and a.connection == b.connection


def move_entries(source, src, destination, dst, entries, cancel, report=lambda *args: None):
    if not getattr(source, 'supports_delete', True):
        raise PermissionError('This device permits copying, but not moving or deleting files.')
    if source.readonly or destination.readonly:
        raise PermissionError('Both source and destination must be writable for moving.')
    if isinstance(source, LocalProvider) and isinstance(destination, LocalProvider):
        return move_local(source, src, destination, dst, entries, cancel, report)
    if same_server(source, destination):
        if dst.rstrip("/") == src.rstrip("/"):
            raise ValueError('Source and destination are the same.')
        with source.batch():
            for entry in entries:
                check(cancel)
                original, target = source.join(src, entry.name), destination.join(dst, entry.name)
                if entry.is_dir and (dst.rstrip("/") + "/").startswith(original.rstrip("/") + "/"):
                    raise ValueError('Cannot move a folder into itself.')
                source.rename(original, target)
                report(f'Moving · {entry.name}', 0)
        return
    # Cross-server moves: copy first, verify every byte and the source tree again,
    # then remove. An interrupted verification leaves both trees intact.
    with source.batch(), destination.batch():
        for entry in entries:
            check(cancel)
            sp, dp = source.join(src, entry.name), destination.join(dst, entry.name)
            snapshot = list(walk(source, sp, cancel)) if entry.is_dir else [(entry.name, sp, entry)]
            if entry.is_link or any(e.is_link for _, _, e in snapshot):
                raise ValueError('Moving symbolic links is not supported.')
            hashes = {n: digest(source, p, cancel) for n, p, e in snapshot if not e.is_dir}
            copy_entries(source, src, destination, dst, [entry], cancel, report)
            after = list(walk(source, sp, cancel)) if entry.is_dir else [(entry.name, sp, next(e for e in source.list(src) if e.name == entry.name))]
            if {n: signature(e) for n, _, e in snapshot} != {n: signature(e) for n, _, e in after}:
                raise RuntimeError('The source changed during the move; it was kept.')
            for name, path, item in after:
                if not item.is_dir:
                    target = relative_path(destination, dp, name) if entry.is_dir else dp
                    if hashes[name] != digest(source, path, cancel) or hashes[name] != digest(destination, target, cancel):
                        raise RuntimeError('Move content verification failed; the source was kept.')
            check(cancel)
            source.remove(sp, entry)
