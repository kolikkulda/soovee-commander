"""Explicit per-peer shared roots and authenticated filesystem RPC."""
import hashlib
import math
import os
import shutil
from pathlib import Path
import tempfile
from threading import RLock
import uuid
from urllib.parse import quote

from .lan_files import is_link, open_regular, relative_path, signature
from .lan_protocol import CHUNK, TransferError, receive_message, send_message
from .lan_store import atomic_json, valid_id
from .providers import LocalProvider, Entry, Provider


class SharedFolders:
    def __init__(self, directory, kind='desktop'):
        self.private_root = Path(directory).resolve()
        self.path = Path(directory) / 'shares.json'
        self.lock = RLock()
        self.denied_paths = []
        self.value = dict(mode='controlled' if kind == 'tv' else 'both', shares=[])
        if self.path.is_symlink():
            raise TransferError('Invalid shared-folder settings.')
        if self.path.exists():
            import json
            self.value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.value, dict) or self.value.get('mode') not in ('both', 'controlled', 'controller') or not isinstance(self.value.get('shares'), list):
                raise TransferError('Invalid shared-folder settings.')
            for item in self.value['shares']:
                if (not isinstance(item, dict) or not isinstance(item.get('path'), str) or not Path(item['path']).is_absolute()
                        or not isinstance(item.get('peers'), list) or type(item.get('writable')) is not bool
                        or not isinstance(item.get('identity'), list) or len(item['identity']) != 2
                        or any(type(value) is not int for value in item['identity'])):
                    raise TransferError('Invalid shared-folder settings.')
                valid_id(item.get('id'))
                if '/' in relative_path(item.get('name')):
                    raise TransferError('Invalid shared-folder settings.')
                for peer in item['peers']:
                    valid_id(peer)
        self.save()

    @property
    def mode(self):
        return self.value['mode']

    def save(self):
        with self.lock:
            atomic_json(self.path, self.value)

    def set_mode(self, mode):
        if mode not in ('both', 'controlled', 'controller'):
            raise TransferError('Invalid device role.')
        with self.lock:
            self.value['mode'] = mode
            self.save()

    def add(self, path, name, peer, writable=False):
        valid_id(peer)
        if '/' in name or relative_path(name) != name:
            raise TransferError('Enter one valid shared-folder name.')
        root = Path(path).resolve(strict=True)
        if not root.is_dir():
            raise TransferError('Choose an existing folder to share.')
        with self.lock:
            if any(item['name'].casefold() == name.casefold() and peer in item['peers'] for item in self.value['shares']):
                raise TransferError('A shared folder already has this name.')
            info = root.stat()
            value = dict(id=uuid.uuid4().hex, path=str(root), name=name, peers=[peer], writable=bool(writable), identity=[info.st_dev, info.st_ino])
            self.value['shares'].append(value)
            self.save()
            return dict(value)

    def remove(self, identity):
        with self.lock:
            self.value['shares'] = [item for item in self.value['shares'] if item['id'] != identity]
            self.save()

    def revoke_peer(self, peer):
        """A removed pairing loses every folder grant; a share left with no device is dropped. Files stay."""
        with self.lock:
            shares = []
            for item in self.value['shares']:
                peers = [value for value in item['peers'] if value != peer]
                if peers:
                    shares.append(dict(item, peers=peers))
            self.value['shares'] = shares
            self.save()

    def available(self, peer):
        with self.lock:
            if self.mode == 'controller':
                return []
            return [dict(id=item['id'], name=item['name'], writable=item['writable']) for item in self.value['shares'] if peer in item['peers']]

    def resolve(self, peer, identity, relative='', write=False):
        with self.lock:
            if self.mode == 'controller':
                raise TransferError('This device does not allow remote browsing.')
            item = next((item for item in self.value['shares'] if item['id'] == identity and peer in item['peers']), None)
            if item is None or write and not item['writable']:
                raise TransferError('This shared folder is unavailable or read only.')
            root = Path(item['path'])
            if not root.is_dir() or any(is_link(parent.lstat()) for parent in [root, *root.parents]):
                raise TransferError('The shared folder was moved or replaced.')
            info = root.stat()
            if [info.st_dev, info.st_ino] != item['identity']:
                raise TransferError('The shared folder was moved or replaced.')
            path = root
            if relative:
                relative_path(relative)
                for part in relative.split('/'):
                    path = path / part
                    if path.exists() or path.is_symlink():
                        if is_link(path.lstat()):
                            raise TransferError('Links are not accessible through a shared folder.')
            if any(path == blocked or blocked in path.parents for blocked in self.denied_paths):
                raise TransferError('The operating system protects this folder.')
            if not path.resolve(strict=False).is_relative_to(root.resolve(strict=True)):
                raise TransferError('The requested path is outside the shared folder.')
            if path.resolve(strict=False).is_relative_to(self.private_root):
                raise TransferError('Application pairing keys cannot be shared.')
            return path


def handle_files(service, sock, peer):
    request = receive_message(sock)
    action = request.get('action')
    if action == 'roots':
        send_message(sock, dict(roots=service.shares.available(peer.id), mode=service.shares.mode))
        return
    relative = request.get('path', '')
    if not isinstance(relative, str):
        raise TransferError('Invalid shared path.')
    write = action in ('put', 'mkdir', 'rename', 'remove')
    path = service.shares.resolve(peer.id, request.get('share'), relative, write=write)
    if action in ('rename', 'remove') and any(path == blocked or path in blocked.parents
            for blocked in [service.shares.private_root, *service.shares.denied_paths]):
        raise TransferError('This item contains a protected folder and cannot be changed.')
    provider = LocalProvider()
    if action == 'space':
        usage = shutil.disk_usage(path)
        total, free, available = usage.total, usage.free, usage.free
        if hasattr(os, 'statvfs'):
            info = os.statvfs(path); block = info.f_frsize or info.f_bsize
            total, free, available = info.f_blocks * block, info.f_bfree * block, info.f_bavail * block
        writable = any(item['id'] == request.get('share') and item['writable'] for item in service.shares.available(peer.id))
        send_message(sock, dict(total=total, free=free, available=available, path=str(path), readonly=not writable or not os.access(path, os.W_OK)))
    elif action == 'list':
        values = provider.list(str(path))
        # Do not advertise links, device nodes or application-private transfer staging.
        result = []
        for entry in values:
            if entry.is_link or entry.name == '.soovee-transfers':
                continue
            try:
                child = service.shares.resolve(peer.id, request.get('share'), '/'.join(filter(None, [relative, entry.name])))
                if not child.is_dir() and not child.is_file():
                    continue
            except TransferError:
                continue
            result.append(dict(name=entry.name, directory=entry.is_dir, size=entry.size, modified=entry.modified))
        send_message(sock, dict(entries=result))
    elif action == 'get':
        with open_regular(path) as stream:
            before = signature(os.fstat(stream.fileno()))
            digest = hashlib.sha256()
            send_message(sock, dict(size=before[2]))
            remaining = before[2]
            while remaining:
                if service.stopping.is_set():
                    raise TransferError('Local transfers are disabled.')
                service.store.get(peer.id)
                service.shares.resolve(peer.id, request.get('share'), relative)
                block = stream.read(min(CHUNK, remaining))
                if not block:
                    raise TransferError('The shared file changed during reading.')
                sock.sendall(block)
                digest.update(block)
                remaining -= len(block)
            if signature(os.fstat(stream.fileno())) != before:
                raise TransferError('The shared file changed during reading.')
            send_message(sock, dict(verified=True, sha256=digest.hexdigest()))
    elif action == 'put':
        size, digest = request.get('size'), request.get('sha256')
        import re
        if type(size) is not int or not 0 <= size < 2**63 or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise TransferError('Invalid upload metadata.')
        if not relative or not path.parent.is_dir() or path.exists():
            raise TransferError('The destination exists or is not a writable file location.')
        if shutil.disk_usage(path.parent).free < size:
            raise TransferError('There is not enough free space at the destination.')
        send_message(sock, dict(ready=True))
        def producer(output):
            remaining, result = size, hashlib.sha256()
            while remaining:
                service.store.get(peer.id)
                service.shares.resolve(peer.id, request.get('share'), relative, write=True)
                if service.stopping.is_set():
                    raise TransferError('Local transfers are disabled.')
                block = sock.recv(min(CHUNK, remaining))
                if not block:
                    raise TransferError('The upload was interrupted.')
                output.write(block)
                result.update(block)
                remaining -= len(block)
            if result.hexdigest() != digest:
                raise TransferError('File integrity verification failed.')
        provider.write_with(str(path), producer, lambda count: service.shares.resolve(peer.id, request.get('share'), relative, write=True), overwrite=False)
        send_message(sock, dict(verified=True))
    elif action == 'mkdir':
        if not relative:
            raise TransferError('Choose a folder inside a shared root.')
        provider.mkdir(str(path))
        send_message(sock, dict(created=True))
    elif action == 'rename':
        destination = request.get('destination')
        if not relative or not isinstance(destination, str) or not destination:
            raise TransferError('Choose an item inside a shared root.')
        target = service.shares.resolve(peer.id, request.get('share'), destination, write=True)
        if target == path or path in target.parents:
            raise TransferError('Choose a different destination outside this folder.')
        provider.rename(str(path), str(target))
        send_message(sock, dict(renamed=True))
    elif action == 'remove':
        if not relative:
            raise TransferError('A shared storage root cannot be deleted.')
        # Validate every descendant before starting: protected trees and links must
        # never become reachable through a recursive delete of their parent.
        candidates = [path]
        while candidates:
            current = candidates.pop()
            child_relative = str(current.relative_to(path)).replace(os.sep, '/')
            checked = relative if child_relative == '.' else relative + '/' + child_relative
            service.store.get(peer.id)
            service.shares.resolve(peer.id, request.get('share'), checked, write=True)
            if current.is_dir():
                candidates.extend(current.iterdir())
        info = path.stat()
        provider.remove(str(path), Entry(path.name, path.is_dir(), info.st_size, info.st_mtime))
        send_message(sock, dict(removed=True))
    else:
        raise TransferError('This remote filesystem operation is not supported.')


class DeviceProvider(Provider):
    """A paired device browsable in a normal Commander panel. No OS drive mount."""
    cache_listings = True
    supports_overwrite = False
    supports_delete = True

    @staticmethod
    def _name(name):
        if '/' in relative_path(name):
            raise TransferError('Invalid remote filename.')
        return name
    def __init__(self, service, peer_id):
        self.service, self.peer_id = service, peer_id
        self.label = 'Soovee · ' + service.store.get(peer_id).name
        self.roots = {}
        self.lock = RLock()

    def _roots(self):
        with self.service.files_connection(self.peer_id) as sock:
            send_message(sock, dict(action='roots'))
            response = receive_message(sock)
        roots = response['roots']
        if not isinstance(roots, list) or len(roots) > 1000:
            raise TransferError('Invalid shared-folder list.')
        names = set()
        for item in roots:
            if not isinstance(item, dict) or type(item.get('writable')) is not bool:
                raise TransferError('Invalid shared-folder list.')
            name = self._name(item.get('name'))
            valid_id(item.get('id'))
            if name.casefold() in names:
                raise TransferError('Duplicate shared-folder name.')
            names.add(name.casefold())
        with self.lock:
            self.roots = {item['name']: item for item in roots}
        return roots

    def _request(self, path, action, **values):
        parts = path.strip('/').split('/')
        if not parts[0]:
            raise TransferError('Choose a shared folder first.')
        relative_path('/'.join(parts))
        roots = {item['name']: item for item in self._roots()}
        if parts[0] not in roots:
            raise TransferError('This shared folder is no longer available.')
        if action in ('put', 'mkdir', 'rename', 'remove') and not roots[parts[0]]['writable']:
            raise TransferError('This shared folder is unavailable or read only.')
        return dict(action=action, share=roots[parts[0]]['id'], path='/'.join(parts[1:]), **values)

    def list(self, path):
        if path == '/':
            return [Entry(item['name'], True) for item in self._roots()]
        request = self._request(path, 'list')
        with self.service.files_connection(self.peer_id) as sock:
            send_message(sock, request)
            entries = receive_message(sock)['entries']
        if not isinstance(entries, list) or len(entries) > 100000:
            raise TransferError('Invalid remote folder listing.')
        result, names = [], set()
        for item in entries:
            if (not isinstance(item, dict) or type(item.get('directory')) is not bool
                    or type(item.get('size')) is not int or not 0 <= item['size'] < 2**63
                    or type(item.get('modified')) not in (int, float) or not math.isfinite(item['modified'])):
                raise TransferError('Invalid remote folder listing.')
            name = self._name(item.get('name'))
            if name in names:
                raise TransferError('Duplicate remote filename.')
            names.add(name)
            result.append(Entry(name, item['directory'], item['size'], item['modified']))
        return result

    def read_to(self, path, output, progress):
        request = self._request(path, 'get')
        with self.service.files_connection(self.peer_id) as sock:
            send_message(sock, request)
            value = receive_message(sock)
            remaining, result = value['size'], hashlib.sha256()
            if type(remaining) is not int or not 0 <= remaining < 2**63:
                raise TransferError('Invalid remote file size.')
            while remaining:
                block = sock.recv(min(CHUNK, remaining))
                if not block:
                    raise TransferError('The download was interrupted.')
                output.write(block)
                result.update(block)
                remaining -= len(block)
                progress(len(block))
            receipt = receive_message(sock)
            if receipt.get('verified') is not True or result.hexdigest() != receipt.get('sha256'):
                raise TransferError('File integrity verification failed.')

    def write_from(self, path, source, progress, overwrite=False):
        if overwrite:
            raise TransferError('Replacing remote files is not enabled. Use a new filename.')
        self._request(path, 'put')  # Check the write grant before staging any bytes.
        # A bounded spool determines size/checksum before granting a write on the peer.
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as staged:
            size, digest = 0, hashlib.sha256()
            while block := source.read(CHUNK):
                progress(0)
                staged.write(block)
                digest.update(block)
                size += len(block)
            request = self._request(path, 'put', size=size, sha256=digest.hexdigest())
            staged.seek(0)
            with self.service.files_connection(self.peer_id) as sock:
                send_message(sock, request)
                if receive_message(sock) != {'ready': True}:
                    raise TransferError('The remote device did not accept the upload.')
                while block := staged.read(CHUNK):
                    sock.sendall(block)
                    progress(len(block))
                if receive_message(sock) != {'verified': True}:
                    raise TransferError('The remote device did not verify the upload.')

    def mkdir(self, path):
        request = self._request(path, 'mkdir')
        with self.service.files_connection(self.peer_id) as sock:
            send_message(sock, request)
            if receive_message(sock) != {'created': True}:
                raise TransferError('The folder could not be created.')

    def rename(self, source, destination):
        request = self._request(source, 'rename')
        target = self._request(destination, 'rename')
        if request['share'] != target['share']:
            raise TransferError('Moving between storage roots requires copying first.')
        request['destination'] = target['path']
        if not request['path'] or not target['path']:
            raise TransferError('Choose an item inside a shared root.')
        with self.service.files_connection(self.peer_id) as sock:
            send_message(sock, request)
            if receive_message(sock) != {'renamed': True}:
                raise TransferError('The item could not be renamed.')

    def remove(self, path, entry):
        request = self._request(path, 'remove')
        if not request['path']:
            raise TransferError('A shared storage root cannot be deleted.')
        with self.service.files_connection(self.peer_id) as sock:
            send_message(sock, request)
            if receive_message(sock) != {'removed': True}:
                raise TransferError('The item could not be deleted.')

    def location(self, path):
        return 'soovee-device://' + self.peer_id + quote(path, safe='/')

    def space(self, path):
        if path == '/':
            roots = self._roots()
            if not roots: return None
            root = next((item for item in roots if item['name'] != 'Shared'), roots[0])
            path = '/' + root['name']
        request = self._request(path, 'space')
        with self.service.files_connection(self.peer_id) as sock:
            send_message(sock, request); value = receive_message(sock)
        if any(type(value.get(key)) is not int for key in ('total', 'free', 'available')) or not 0 <= value['available'] <= value['free'] <= value['total']:
            raise TransferError('Invalid device capacity information.')
        if type(value.get('readonly')) is not bool or not isinstance(value.get('path'), str):
            raise TransferError('Invalid device capacity information.')
        value['name'] = path.strip('/').split('/')[0]
        return value
