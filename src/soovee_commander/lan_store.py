"""Private local identity and paired-device state. Secrets never enter QR or logs."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import socket
import tempfile
from threading import RLock
import uuid

from .lan_protocol import TransferError, key_bytes, key_text, local_address
from .nativefs import is_junction


class HeadlessProfileLock:
    """Kernel-owned lock for mobile runtimes without Qt; crash-safe and nonblocking."""
    def __init__(self, path):
        self.path = Path(path).with_suffix('.guard')
        self.descriptor = None

    def tryLock(self, timeout):
        import fcntl
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os,'O_NOFOLLOW',0), 0o600)
        try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor); return False
        self.descriptor = descriptor
        return True

    def unlock(self):
        if self.descriptor is not None:
            os.close(self.descriptor); self.descriptor = None


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise TransferError('Invalid device identity.')
    return value


def valid_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 80 or any(ord(c) < 32 for c in value):
        raise TransferError('Enter a device name with 1 to 80 printable characters.')
    return value.strip()


def private_directory(path):
    path = Path(path)
    if path.is_symlink() or is_junction(path):
        raise TransferError('The transfer state folder must not be a symbolic link.')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        path.chmod(0o700)
    return path


def atomic_json(path, value):
    descriptor, filename = tempfile.mkstemp(prefix='.soovee-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


@dataclass(frozen=True)
class Peer:
    id: str
    name: str
    host: str
    port: int
    secret: bytes = field(repr=False)

    def __post_init__(self):
        valid_id(self.id)
        valid_name(self.name)
        local_address(self.host)
        if type(self.port) is not int or not 1 <= self.port <= 65535 or len(self.secret) != 32:
            raise TransferError('Invalid paired device.')


class DeviceStore:
    def __init__(self, directory, name=None):
        self.directory = private_directory(directory)
        self.path = self.directory / 'devices.json'
        self.lock = RLock()
        if self.path.is_symlink():
            raise TransferError('Invalid device state file.')
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            self.id, self.name = valid_id(value['id']), valid_name(value['name'])
            self._peers = {p['id']: Peer(p['id'], p['name'], p['host'], p['port'], key_bytes(p['secret'])) for p in value.get('peers', [])}
        else:
            self.id = uuid.uuid4().hex
            self.name = valid_name(name or socket.gethostname()[:80] or 'Soovee device')
            self._peers = {}
            self.save()
        if name is not None:
            self.name = valid_name(name)
            self.save()

    def save(self):
        with self.lock:
            atomic_json(self.path, dict(id=self.id, name=self.name, peers=[dict(id=p.id, name=p.name, host=p.host, port=p.port, secret=key_text(p.secret)) for p in self._peers.values()]))

    def peers(self):
        with self.lock:
            return list(self._peers.values())

    def get(self, identity):
        with self.lock:
            if identity not in self._peers:
                raise TransferError('This device is not paired or its permission was removed.')
            return self._peers[identity]

    def add(self, peer):
        if peer.id == self.id:
            raise TransferError('A device cannot pair with itself. Use separate profiles for a local test.')
        with self.lock:
            old = self._peers.get(peer.id)
            if old is not None and old.secret != peer.secret:
                raise TransferError('Remove the old pairing before changing this device identity.')
            self._peers[peer.id] = peer
            self.save()

    def remove(self, identity):
        with self.lock:
            self._peers.pop(identity, None)
            self.save()
