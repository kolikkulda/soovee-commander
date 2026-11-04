"""Manifest validation, stable source reads and resumable atomic receive bundles."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from threading import Event

from .lan_protocol import CHUNK, TransferError, VERSION, canonical
from .lan_store import private_directory, atomic_json
from .nativefs import rename_no_replace, is_junction
from .operations import Cancelled

MAX_ITEMS = 10000


def check(cancel):
    if cancel.is_set():
        raise Cancelled('Transfer canceled. Partial data can be resumed after approval.')


def relative_path(text):
    if not isinstance(text, str) or not text or len(text.encode('utf-8')) > 2048:
        raise TransferError('Invalid transfer filename.')
    parts = text.split('/')
    if len(parts) > 32:
        raise TransferError('The folder tree is too deep.')
    for part in parts:
        if (part in ('', '.', '..') or len(part.encode('utf-8')) > 255 or part.endswith((' ', '.')) or
                any(ord(c) < 32 or c in '\\:*?"<>|' for c in part) or
                re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)):
            raise TransferError('The transfer contains an unsafe or unsupported filename.')
    return text


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode


def open_regular(path):
    before = os.lstat(path)
    if is_link(before) or not stat.S_ISREG(before.st_mode):
        raise TransferError('Only regular files can be transferred.')
    descriptor = os.open(path, getattr(os, 'O_NONBLOCK', 0) | os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise TransferError('Only regular files can be transferred.')
    return os.fdopen(descriptor, 'rb')


def stream_hash(stream, cancel, length=None):
    result = hashlib.sha256()
    remaining = length
    while remaining is None or remaining:
        check(cancel)
        block = stream.read(CHUNK if remaining is None else min(CHUNK, remaining))
        if not block:
            if remaining:
                raise TransferError('The source or partial file was truncated.')
            break
        result.update(block)
        if remaining is not None:
            remaining -= len(block)
    return result.hexdigest()


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {'version', 'items'} or type(manifest['version']) is not int or manifest['version'] != VERSION:
        raise TransferError('Unsupported transfer description.')
    items = manifest['items']
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise TransferError('A transfer must contain 1 to 10000 items.')
    paths, normalized, total = {}, set(), 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {'path', 'kind', 'size', 'sha256', 'mtime_ns'}:
            raise TransferError('Invalid file description.')
        path = relative_path(item['path'])
        if path.casefold() in normalized:
            raise TransferError('The transfer contains duplicate or case-conflicting names.')
        normalized.add(path.casefold())
        paths[path] = item
        if item['kind'] not in ('file', 'directory') or type(item['size']) is not int or not 0 <= item['size'] < 2**63 or type(item['mtime_ns']) is not int or not 0 <= item['mtime_ns'] < 2**63:
            raise TransferError('Invalid file metadata.')
        if not isinstance(item['sha256'], str) or (item['kind'] == 'file' and not re.fullmatch('[a-f0-9]{64}', item['sha256'])) or (item['kind'] == 'directory' and (item['size'] or item['sha256'])):
            raise TransferError('Invalid file checksum.')
        total += item['size']
    if total >= 2**63:
        raise TransferError('The transfer is too large.')
    for path in paths:
        parent = PurePosixPath(path).parent
        while str(parent) != '.':
            if str(parent) not in paths or paths[str(parent)]['kind'] != 'directory':
                raise TransferError('The transfer contains a missing or conflicting parent folder.')
            parent = parent.parent
    return total


@dataclass
class SourcePlan:
    manifest: dict
    sources: dict

    @property
    def id(self):
        return hashlib.sha256(canonical(self.manifest)).hexdigest()

    def open(self, item):
        path, expected = self.sources[item['path']]
        stream = open_regular(path)
        if signature(os.fstat(stream.fileno())) != expected:
            stream.close()
            raise TransferError('The source changed. Prepare a new transfer.')
        return stream


def plan_sources(paths, cancel=None, report=lambda *args: None):
    cancel = cancel or Event()
    records, sources = [], {}
    pending = [(Path(p).absolute(), Path(p).name) for p in paths]
    if not pending:
        raise TransferError('Choose at least one file or folder.')
    while pending:
        check(cancel)
        path, relative = pending.pop()
        relative_path(relative)
        info = path.lstat()
        if is_link(info) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise TransferError('Symbolic links and special files are not supported by Soovee Transfers.')
        directory = stat.S_ISDIR(info.st_mode)
        digest = ''
        if directory:
            with os.scandir(path) as entries:
                children = list(entries)
            pending.extend((path / child.name, relative + '/' + child.name) for child in children)
        else:
            report('Hashing source: ' + relative, 0)
            with open_regular(path) as stream:
                if signature(os.fstat(stream.fileno())) != signature(info):
                    raise TransferError('The source changed while preparing the transfer.')
                digest = stream_hash(stream, cancel)
                if signature(os.fstat(stream.fileno())) != signature(info):
                    raise TransferError('The source changed while preparing the transfer.')
            sources[relative] = (path, signature(info))
        records.append(dict(path=relative, kind='directory' if directory else 'file', size=0 if directory else info.st_size, sha256=digest, mtime_ns=max(0, info.st_mtime_ns)))
        if len(records) + len(pending) > MAX_ITEMS:
            raise TransferError('Narrow the transfer to at most 10000 items.')
    manifest = dict(version=VERSION, items=sorted(records, key=lambda item: item['path']))
    validate_manifest(manifest)
    return SourcePlan(manifest, sources)


class ReceiveBundle:
    def __init__(self, destination, peer_id, manifest, cancel):
        self.total = validate_manifest(manifest)
        self.manifest, self.cancel = manifest, cancel
        self.id = hashlib.sha256(canonical(manifest)).hexdigest()
        self.root = Path(destination).resolve(strict=True)
        if not self.root.is_dir():
            raise TransferError('Choose an existing receiving folder.')
        namespace = private_directory(self.root / '.soovee-transfers')
        self.work = private_directory(namespace / hashlib.sha256((peer_id + self.id).encode()).hexdigest())
        self.output = self.root / ('Soovee-' + self.id[:12])
        self.files = [item for item in manifest['items'] if item['kind'] == 'file']
        self.file_indexes = {item['path']: index for index, item in enumerate(self.files)}
        self.already_complete = False
        if self.output.exists() or self.output.is_symlink():
            self.verify_tree(self.output)
            self.already_complete = True
        required = sum(max(0, item['size'] - self.partial_info(index)[0]) for index, item in enumerate(self.files))
        if not self.already_complete and shutil.disk_usage(self.root).free < required:
            raise TransferError('There is not enough free space at the destination.')

    def partial(self, index):
        return self.work / f'{index:06d}.part'

    def partial_info(self, index):
        path = self.partial(index)
        if path.is_symlink():
            raise TransferError('Invalid partial transfer file.')
        if not path.exists():
            return 0, hashlib.sha256(b'').hexdigest()
        with open_regular(path) as stream:
            length = os.fstat(stream.fileno()).st_size
            if length > self.files[index]['size']:
                raise TransferError('The partial file is larger than the expected file.')
            return length, stream_hash(stream, self.cancel)

    def receive_file(self, index, offset, sock, report):
        item, path = self.files[index], self.partial(index)
        if offset not in (0, self.partial_info(index)[0]):
            raise TransferError('The resume position changed.')
        descriptor = os.open(path, getattr(os, 'O_NONBLOCK', 0) | os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or (offset and info.st_size != offset):
                raise TransferError('The partial file changed.')
            if not offset:
                os.ftruncate(descriptor, 0)
            os.lseek(descriptor, offset, os.SEEK_SET)
            with os.fdopen(descriptor, 'wb') as stream:
                descriptor = None
                position = offset
                while position < item['size']:
                    check(self.cancel)
                    block = sock.recv(min(CHUNK, item['size'] - position))
                    if not block:
                        raise TransferError('The connection was interrupted. Retry to resume the transfer.')
                    stream.write(block)
                    position += len(block)
                    report(position)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor is not None:
                os.close(descriptor)
        with open_regular(path) as stream:
            verified = stream_hash(stream, self.cancel) == item['sha256']
        if not verified:
            path.unlink()
            raise TransferError('File integrity verification failed. No received bundle was published.')

    def verify_tree(self, directory):
        if directory.is_symlink() or is_junction(directory) or not directory.is_dir():
            raise TransferError('The receiving name is already occupied. Choose another destination.')
        expected = {item['path']: item for item in self.manifest['items']}
        observed = set()
        for base, directories, files in os.walk(directory, followlinks=False):
            for name in directories + files:
                check(self.cancel)
                path = Path(base) / name
                relative = path.relative_to(directory).as_posix()
                info = path.lstat()
                item = expected.get(relative)
                if item is None or is_link(info) or (item['kind'] == 'directory') != stat.S_ISDIR(info.st_mode):
                    raise TransferError('An existing receiving bundle differs. Choose another destination.')
                if item['kind'] == 'file':
                    with open_regular(path) as stream:
                        if info.st_size != item['size'] or stream_hash(stream, self.cancel) != item['sha256']:
                            raise TransferError('An existing receiving bundle differs. Choose another destination.')
                observed.add(relative)
        if observed != set(expected):
            raise TransferError('An existing receiving bundle is incomplete. Choose another destination.')

    def publish(self):
        check(self.cancel)
        if self.already_complete:
            return self.output
        payload = self.work / 'payload'
        if payload.is_symlink() or is_junction(payload):
            raise TransferError('Invalid staging folder.')
        if payload.exists():
            # This private assembly can remain after a crash. Verified flat parts are authoritative.
            shutil.rmtree(payload)
        payload.mkdir(mode=0o700)
        try:
            for item in sorted(self.manifest['items'], key=lambda item: (len(PurePosixPath(item['path']).parts), item['path'])):
                check(self.cancel)
                path = payload.joinpath(*item['path'].split('/'))
                if item['kind'] == 'directory':
                    path.mkdir()
                else:
                    index = self.file_indexes[item['path']]
                    with open_regular(self.partial(index)) as stream:
                        if stream_hash(stream, self.cancel) != item['sha256']:
                            raise TransferError('File integrity verification failed.')
                    # Hard links avoid a second full copy on local filesystems.
                    try:
                        os.link(self.partial(index), path)
                    except OSError:
                        with open_regular(self.partial(index)) as source, path.open('xb') as target:
                            while block := source.read(CHUNK):
                                check(self.cancel)
                                target.write(block)
                            target.flush()
                            os.fsync(target.fileno())
                    os.utime(path, ns=(item['mtime_ns'], item['mtime_ns']))
            self.verify_tree(payload)
            if not rename_no_replace(payload, self.output):
                raise TransferError('This destination does not support safe bundle publication. Choose another disk.')
        except BaseException:
            if payload.is_dir() and not payload.is_symlink():
                shutil.rmtree(payload)
            raise
        atomic_json(self.work / 'receipt.json', dict(id=self.id, completed=True))
        for index in range(len(self.files)):
            self.partial(index).unlink(missing_ok=True)
        return self.output
