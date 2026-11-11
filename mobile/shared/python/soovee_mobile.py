"""Native mobile/TV bridge to the authenticated desktop transfer backend."""
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
import socket
import sys
from threading import Event, RLock
import time

import qrcode

from soovee_commander.lan import TransferService
from soovee_commander.lan_protocol import PairingNotRecognized, key_fingerprint, parse_invitation, require_tls_psk
from soovee_commander.device_files import DeviceProvider
from soovee_commander.providers import LocalProvider
from soovee_commander.operations import copy_entries
from soovee_commander.nativefs import rename_no_replace
from soovee_commander.providers import safe_name
from soovee_commander.diagnostic_log import configure, logger
from soovee_commander.lan_store import atomic_json, valid_name
from soovee_commander.discovery import verify_endpoint

service = None
shared = None
callbacks = None
pending_shares = set()
qr_cache = ('', None)
lifecycle_lock = RLock()
storage_roots = []
storage_sharing = False
operation_cancel = Event()
operation_lock = RLock()
operation_state = {}


def runtime_check():
    import ssl
    require_tls_psk()
    return 'TLS-PSK ready · ' + ssl.OPENSSL_VERSION


_WIFI_FIRST = ('en0', 'wlan0')          # iPhone/iPad and Android Wi-Fi
_NOT_LOCAL = ('pdp_ip', 'rmnet', 'ccmni', 'utun', 'ipsec', 'tun', 'ppp', 'awdl', 'llw', 'lo', 'bridge', 'ap')


def _interfaces():
    """(name, IPv4) of each interface via getifaddrs; empty when unavailable."""
    import ctypes, ctypes.util
    class IfAddrs(ctypes.Structure):
        pass
    IfAddrs._fields_ = [('next', ctypes.POINTER(IfAddrs)), ('name', ctypes.c_char_p), ('flags', ctypes.c_uint),
                        ('addr', ctypes.c_void_p), ('netmask', ctypes.c_void_p)]
    try:
        libc = ctypes.CDLL(ctypes.util.find_library('c') or None)
    except OSError:
        return []
    head = ctypes.POINTER(IfAddrs)()
    if libc.getifaddrs(ctypes.byref(head)) != 0:
        return []
    bsd = sys.platform in ('darwin', 'ios', 'tvos')
    result, item = [], head
    try:
        while item:
            entry = item.contents
            if entry.addr:
                raw = ctypes.string_at(entry.addr, 8)
                family = raw[1] if bsd else int.from_bytes(raw[0:2], sys.byteorder)
                if family == socket.AF_INET:
                    result.append((entry.name.decode(errors='replace'), socket.inet_ntoa(raw[4:8])))
            item = entry.next
    finally:
        libc.freeifaddrs(head)
    return result


def _private(address):
    import ipaddress
    value = ipaddress.ip_address(address)
    return value.is_private and not (value.is_loopback or value.is_link_local)


def local_addresses():
    """Wi-Fi/LAN addresses other devices can reach, Wi-Fi first.

    The interface carrying internet traffic may be mobile data or a VPN, whose
    address a computer at home cannot reach, so it is not used blindly.
    """
    try:
        found = [(name, address) for name, address in _interfaces()
                 if _private(address) and not name.startswith(_NOT_LOCAL)]
    except Exception:
        found = []
    found.sort(key=lambda item: (item[0] not in _WIFI_FIRST, item[0]))
    values = list(dict.fromkeys(address for name, address in found))
    if not values:
        try:  # Fallback where getifaddrs is unavailable (tests, unusual platforms).
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(('192.0.2.1', 9))
                if _private(sock.getsockname()[0]):
                    values.append(sock.getsockname()[0])
        except OSError:
            pass
    return values or ['127.0.0.1']


def on_local_network():
    return local_addresses() != ['127.0.0.1']


def start(state, folder, name, kind, bridge):
    with lifecycle_lock:
        return _start(state, folder, name, kind, bridge)


def _start(state, folder, name, kind, bridge):
    global service, shared, callbacks, storage_roots, storage_sharing
    runtime_check()
    callbacks = bridge
    if service is not None:
        return snapshot()
    storage_roots, storage_sharing = [], False
    configure(Path(state) / 'logs')
    shared = Path(folder); shared.mkdir(parents=True, exist_ok=True)
    storage_roots = [dict(key='app', name='Shared', path=str(shared), writable=True)]

    def approve(peer):
        accepted = bool(callbacks.approve('pair', json.dumps(dict(name=peer.name, host=peer.host,
                           verification=key_fingerprint(peer.secret), storageSharing=storage_sharing), ensure_ascii=False)))
        if accepted:
            pending_shares.add(peer.id)
        return accepted

    def offer(peer, manifest, cancel):
        accepted = bool(callbacks.approve('receive', json.dumps(dict(name=peer.name,
            files=len(manifest['items']), bytes=sum(i['size'] for i in manifest['items'])), ensure_ascii=False)))
        return shared if accepted and not cancel.is_set() else None

    def event(value):
        if value['kind'] == 'error':
            logger.error('Transfer failed: %s', value.get('message', ''), exc_info=True)
        if value['kind'] == 'paired' and value['device'] in pending_shares:
            pending_shares.discard(value['device'])
            if not service.shares.available(value['device']):
                service.shares.add(shared, 'Shared', value['device'], writable=True)
            sync_storage_peer(value['device'])
        callbacks.activity(json.dumps(value, ensure_ascii=False))

    state = Path(state)
    service = TransferService(state, None if (state / 'devices.json').exists() else name, approve_pair=approve, approve_offer=offer,
                              event=event, device_kind=kind)
    endpoint = state / 'listener.json'
    try:
        port = json.loads(endpoint.read_text(encoding='utf-8')).get('port', 0)
        if type(port) is not int or not 0 < port <= 65535: port = 0
    except (OSError, ValueError, AttributeError):
        port = 0
    try: service.start('0.0.0.0', port)
    except OSError: service.start('0.0.0.0', 0)
    atomic_json(endpoint, dict(port=service.port))
    service.begin_pairing()
    return snapshot()


def snapshot(host=None):
    global qr_cache
    if service is None:
        return json.dumps(dict(enabled=False))
    address = host or local_addresses()[0]
    session = service.pairing
    active = session is not None and session['expires'] > time.monotonic() and session['attempts'] < 5
    result = dict(enabled=True, id=service.store.id, name=service.store.name, address=address, port=service.port,
                  localNetwork=address != '127.0.0.1',
                  folder=str(shared), role=service.shares.mode, code=session['code'] if active else '',
                  storage=storage_snapshot(), storageSharing=storage_sharing, pairRequests=service.accept_pair_requests,
                  expires=max(0, int(session['expires'] - time.monotonic())) if active else 0,
                  peers=[dict(id=p.id, name=p.name, host=p.host, port=p.port) for p in service.store.peers()])
    if active:
        result['invitation'] = service.pairing_link(address)
        if qr_cache[0] != result['invitation']:
            code = qrcode.QRCode(border=4); code.add_data(result['invitation']); code.make(fit=True)
            qr_cache = (result['invitation'], code.get_matrix())
        result['qr'] = qr_cache[1]
    return json.dumps(result, ensure_ascii=False)


def renew():
    service.begin_pairing()
    return snapshot()


def set_role(role):
    service.shares.set_mode(role)
    return snapshot()


def set_pair_requests(enabled):
    service.set_pair_requests(enabled is True or str(enabled).lower() in ('true', '1'))
    return snapshot()


def set_name(name):
    service.store.name = valid_name(name)
    service.store.save()
    return snapshot()


def pair(invitation, host='', port='0', code=''):
    if invitation.strip():
        host, port, code = parse_invitation(invitation)
    def approve(peer):
        accepted = bool(callbacks.approve('pair', json.dumps(dict(name=peer.name, host=peer.host,
                             verification=key_fingerprint(peer.secret), storageSharing=storage_sharing), ensure_ascii=False)))
        if accepted: pending_shares.add(peer.id)
        return accepted
    logger.info('Native pairing started')
    try:
        peer=service.pair(host, int(port), ''.join(code.split()), approve=approve)
        value=json.loads(snapshot());value['pairedDevice']=peer.id
        logger.info('Native pairing completed')
        return json.dumps(value,ensure_ascii=False)
    except Exception:
        logger.exception('Native pairing failed')
        raise


def reconnect(identity, host, port):
    """Adopt a rediscovered address once the device proves it holds our key.

    Never raises: connection_status then tells the user what is wrong (for
    example that the other device removed the pairing) and offers what to do.
    """
    try:
        verify_endpoint(service, identity, host, int(port))
        not_recognized.discard(identity)
    except PairingNotRecognized:
        not_recognized.add(identity)
    except Exception:
        logger.exception('Paired device did not verify at its new address')
    return snapshot()


not_recognized = set()   # devices that refused our key at their current address


def connection_status(identity):
    """Pairing and a usable shared filesystem are distinct, explicit states."""
    peer=service.store.get(identity)
    try:
        roots=DeviceProvider(service,identity).list('/')
        return json.dumps(dict(id=identity,name=peer.name,status='ready' if roots else 'no_shared_folders',
                               roots=[entry.name for entry in roots]),ensure_ascii=False)
    except PairingNotRecognized as error:
        return json.dumps(dict(id=identity,name=peer.name,status='not_recognized',message=str(error)),ensure_ascii=False)
    except Exception as error:
        if identity in not_recognized:   # the old address is gone and the new one refused our key
            return json.dumps(dict(id=identity,name=peer.name,status='not_recognized',message=str(error)),ensure_ascii=False)
        logger.exception('Native paired-device connection failed')
        return json.dumps(dict(id=identity,name=peer.name,status='unavailable',message=str(error)),ensure_ascii=False)


def configure_storage(roots, enabled):
    """Called only by native UI after its explicit storage-sharing consent flow."""
    global storage_roots, storage_sharing
    values = json.loads(roots)
    if not isinstance(values, list) or len(values) > 32: raise ValueError('Invalid storage list.')
    result = []
    for value in values:
        key, name = value.get('key'), value.get('name')
        if not isinstance(key, str) or not key or len(key) > 100: raise ValueError('Invalid storage identity.')
        safe_name(name)
        path = Path(value['path']).resolve(strict=True)
        if not path.is_dir() or path.is_relative_to(service.store.directory.resolve()):
            raise ValueError('The transfer state folder cannot be shared.')
        result.append(dict(key=key, name=name, path=str(path), writable=value.get('writable') is True, shared=value.get('shared',True) is True))
    if len({value['key'] for value in result}) != len(result): raise ValueError('Duplicate storage identity.')
    if len({value['name'].casefold() for value in result}) != len(result): raise ValueError('Duplicate storage name.')
    with lifecycle_lock:
        storage_roots = result; storage_sharing = bool(enabled)
        service.shares.denied_paths = [Path(value['path']) / 'Android' / child for value in result if value['key'] != 'app' for child in ('data','obb')]
        for peer in service.store.peers(): sync_storage_peer(peer.id)
    return snapshot()


def sync_storage_peer(identity):
    with lifecycle_lock:
        current = service
        if current is None: return
        with current.shares.lock:
            desired = {item['key']:item for item in storage_roots if item['key'] == 'app' or storage_sharing and item.get('shared',True)}
            for item in list(current.shares.value['shares']):
                if identity not in item['peers']: continue
                key = item.get('mobile_root')
                if key is None and Path(item['path']).resolve() == shared.resolve() and item['name'] == 'Shared':
                    key = item['mobile_root'] = 'app'
                if key is not None and key != 'app' and key not in desired:
                    current.shares.value['shares'].remove(item)
            for key, root in desired.items():
                existing = next((item for item in current.shares.value['shares'] if identity in item['peers'] and item.get('mobile_root') == key), None)
                path = Path(root['path']); info = path.stat()
                if existing is None:
                    value = current.shares.add(path, root['name'], identity, writable=root['writable'])
                    existing = next(item for item in current.shares.value['shares'] if item['id'] == value['id'])
                existing.update(mobile_root=key, path=str(path), name=root['name'], writable=root['writable'], identity=[info.st_dev,info.st_ino])
            current.shares.save()

def storage_snapshot():
    values = storage_roots or ([dict(key='app',name='Shared',path=str(shared),writable=True)] if shared else [])
    result = []
    for root in values:
        value = dict(root)
        try:
            usage = shutil.disk_usage(root['path']); value.update(total=usage.total,free=usage.free)
        except OSError: value.update(total=0,free=0)
        value['shared'] = root['key'] == 'app' or storage_sharing and root.get('shared',True)
        result.append(value)
    return result


def browse_local(root, path='/'):
    value = next((item for item in storage_roots if item['key'] == root), None)
    if value is None: raise ValueError('This storage is unavailable.')
    base = Path(value['path']); target = base / path.lstrip('/')
    if not target.resolve().is_relative_to(base.resolve()): raise ValueError('The path is outside this storage.')
    if root != 'app' and (target == base / 'Android' / 'data' or target == base / 'Android' / 'obb' or any((base / 'Android' / child) in target.parents for child in ('data','obb'))):
        raise ValueError('Android protects other applications’ private files.')
    entries = sorted(LocalProvider().list(str(target)), key=lambda item:(not item.is_dir,item.name.casefold()))
    return json.dumps([dict(name=item.name,directory=item.is_dir,bytes=item.size,modified=item.modified) for item in entries if not item.is_link],ensure_ascii=False)


def local_location(path):
    parts = path.strip('/').split('/')
    root = next((value for value in storage_roots if value['name'] == parts[0]), None)
    if root is None: raise ValueError('Choose a storage folder first.')
    for part in parts[1:]: safe_name(part)
    base = Path(root['path']); target = base.joinpath(*parts[1:])
    current = base
    for part in parts[1:]:
        current = current / part
        if current.is_symlink(): raise ValueError('Links are not accessible through a shared folder.')
    if not target.resolve().is_relative_to(base.resolve()): raise ValueError('The path is outside this storage.')
    if any(target == blocked or blocked in target.parents for blocked in service.shares.denied_paths):
        raise ValueError('Android protects other applications’ private files.')
    if target.resolve().is_relative_to(service.store.directory.resolve()):
        raise ValueError('The transfer state folder cannot be opened.')
    return root, target


def browse_local_path(path='/'):
    if path == '/':
        return json.dumps([dict(name=value['name'],directory=True,bytes=0) for value in storage_roots],ensure_ascii=False)
    root, target = local_location(path)
    relative = str(target.relative_to(Path(root['path']))).replace(os.sep,'/')
    return browse_local(root['key'], '/' if relative == '.' else '/' + relative)


def local_file(path):
    return str(local_location(path)[1])


def download_to(peer, source, destination):
    root, target = local_location(destination)
    if not root['writable']: raise ValueError('This storage is read only.')
    provider = DeviceProvider(service, peer)
    entry = next(value for value in provider.list(provider.parent(source)) if value.name == source.rsplit('/',1)[-1])
    copy_entries(provider, provider.parent(source), LocalProvider(), str(target), [entry], Event())
    return str(target / entry.name)


def upload_from(peer, destination, source):
    root, path = local_location(source)
    provider = LocalProvider()
    entry = next(value for value in provider.list(str(path.parent)) if value.name == path.name)
    copy_entries(provider, str(path.parent), DeviceProvider(service,peer), destination, [entry], Event())
    return snapshot()


def delete_local_path(path):
    root, target = local_location(path)
    if target == Path(root['path']) or not root['writable']: raise ValueError('This storage root cannot be deleted.')
    if any(target == blocked or target in blocked.parents for blocked in [service.store.directory.resolve(),*service.shares.denied_paths]):
        raise ValueError('This item contains a protected folder and cannot be changed.')
    provider = LocalProvider()
    entry = next(value for value in provider.list(str(target.parent)) if value.name == target.name)
    provider.remove(str(target), entry)
    return snapshot()


def mutate_item(peer, path, action, name=''):
    """Native file actions; roots and write grants are checked by the same core."""
    if action not in ('rename','remove','mkdir','newfile'): raise ValueError('Unsupported file action.')
    if action=='newfile':
        # An empty file, never replacing an existing one (local storage only).
        if peer: raise ValueError('Unsupported file action.')
        root,target=local_location(path)
        if not root['writable']: raise ValueError('This storage is read only.')
        with open(target/safe_name(name),'x',encoding='utf-8'): pass
        return snapshot()
    if peer:
        provider=DeviceProvider(service,peer)
        if action=='mkdir': provider.mkdir(provider.join(path,safe_name(name)))
        elif action=='rename': provider.rename(path,provider.join(provider.parent(path),safe_name(name)))
        else: provider.remove(path,None)
    else:
        root,target=local_location(path)
        if not root['writable']: raise ValueError('This storage is read only.')
        provider=LocalProvider()
        if action=='mkdir': provider.mkdir(str(target/safe_name(name)))
        elif action=='remove': return delete_local_path(path)
        else:
            if target==Path(root['path']) or any(target==blocked or target in blocked.parents for blocked in [service.store.directory.resolve(),*service.shares.denied_paths]):
                raise ValueError('This storage root or protected folder cannot be renamed.')
            provider.rename(str(target),str(target.parent/safe_name(name)))
    return snapshot()


def preview_copy(peer, source):
    """Copy a file from a paired device into a private cache so iOS can preview or share it."""
    cache = Path(tempfile.gettempdir()) / 'soovee-preview'
    shutil.rmtree(cache, ignore_errors=True); cache.mkdir(parents=True, exist_ok=True)
    provider = DeviceProvider(service, peer)
    name = PurePosixPath(source).name
    entry = next(value for value in provider.list(provider.parent(source)) if value.name == name)
    if entry.is_dir: raise ValueError('Choose a file to preview.')
    copy_entries(provider, provider.parent(source), LocalProvider(), str(cache), [entry], Event())
    return str(cache / name)


def copy_local_item(source, destination, moving=False):
    from soovee_commander.operations import move_local
    source_root,original=local_location(source)
    target_root,target=local_location(destination)
    if original==Path(source_root['path']): raise ValueError('Choose an item inside a storage folder.')
    if not target_root['writable'] or moving and not source_root['writable']: raise ValueError('This storage is read only.')
    if any(original==blocked or original in blocked.parents for blocked in [service.store.directory.resolve(),*service.shares.denied_paths]):
        raise ValueError('This item contains a protected folder and cannot be changed.')
    provider=LocalProvider();entry=next(value for value in provider.list(str(original.parent)) if value.name==original.name)
    last=[0.0]; transferred=[0]
    def report(message,count):
        transferred[0]+=count
        if time.monotonic()-last[0]>.15:
            last[0]=time.monotonic()
            callbacks.activity(json.dumps(dict(kind='operation',message=str(original)+' → '+str(target),bytes=transferred[0])))
    (move_local if moving else copy_entries)(provider,str(original.parent),provider,str(target),[entry],Event(),report)
    logger.info('Native %s completed · %s → %s','move' if moving else 'copy',source,destination)
    return snapshot()


ARCHIVE_SUFFIXES = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.zip', '.tar')


def _protected(target):
    return any(target == blocked or blocked in target.parents for blocked in [service.store.directory.resolve(), *service.shares.denied_paths])


def _free_path(folder, name):
    """folder/name, or folder/name (2), (3)… when that already exists."""
    candidate = folder / name
    stem, suffix = (name, '') if '.' not in name[1:] else (name.rsplit('.', 1)[0], '.' + name.rsplit('.', 1)[1])
    number = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = folder / f'{stem} ({number}){suffix}'; number += 1
    return candidate


def _run_operation(action, files, destination, work):
    """Shared progress, cancel and logging for long local operations (archives)."""
    global operation_state
    with operation_lock:
        operation_cancel.clear()
        operation_state = dict(status='running', action=action, files=files, completed=0, bytes=0, destination=destination)
        last = [0.0]
        def report(message, count):
            operation_state['bytes'] += count
            if not message.startswith('@'): operation_state['current'] = message
            elif message.startswith('@transfer:'):
                detail = json.loads(message[len('@transfer:'):])
                if detail.get('event') == 'plan':
                    operation_state['total'] = operation_state.get('total', 0) + int(detail.get('bytes') or 0)
                    operation_state['total_files'] = operation_state.get('total_files', 0) + int(detail.get('files') or 0)
                elif detail.get('event') == 'file': operation_state['current'] = detail.get('source', '')
            if time.monotonic() - last[0] > .1:
                last[0] = time.monotonic()
                callbacks.activity(json.dumps(dict(kind='operation', **operation_state), ensure_ascii=False))
        try:
            result = work(report)
            operation_state.update(status='done', completed=files)
            return result
        except Exception as error:
            operation_state.update(status='canceled' if operation_cancel.is_set() else 'error', message=str(error))
            logger.exception('Native %s failed', action)
            raise
        finally:
            callbacks.activity(json.dumps(dict(kind='operation', **operation_state), ensure_ascii=False))


def duplicate_item(path):
    """A copy next to the original with a free name, such as "Report (2).txt"."""
    from soovee_commander.operations import Cancelled
    root, original = local_location(path)
    if not root['writable']: raise ValueError('This storage is read only.')
    if original == Path(root['path']) or _protected(original) or original.is_symlink():
        raise ValueError('This storage root or protected folder cannot be copied or moved.')
    target = _free_path(original.parent, original.name)
    files = [original] if original.is_file() else [item for item in original.rglob('*') if item.is_file() and not item.is_symlink()]
    def work(report):
        total = sum(item.stat().st_size for item in files)
        report('@transfer:' + json.dumps(dict(event='plan', bytes=total, files=len(files))), 0)
        def copy_file(source, destination):
            report(str(source), 0)
            with open(source, 'rb') as reader, open(destination, 'xb') as writer:
                while block := reader.read(1024 * 1024):
                    if operation_cancel.is_set(): raise Cancelled('Copy canceled.')
                    writer.write(block); report('@', len(block))
            info = source.stat(); os.utime(destination, ns=(info.st_atime_ns, info.st_mtime_ns))   # not copystat: Android forbids copying SELinux attributes
        try:
            if original.is_file(): copy_file(original, target)
            else:
                for folder in [original, *sorted(item for item in original.rglob('*') if item.is_dir() and not item.is_symlink())]:
                    (target / folder.relative_to(original)).mkdir(parents=True, exist_ok=True)
                for item in files:
                    copy_file(item, target / item.relative_to(original))
                    operation_state['completed'] = operation_state.get('completed', 0) + 1
        except BaseException:
            shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(missing_ok=True)
            raise
        logger.info('Native duplicate completed · %s → %s', path, target.name)
        return json.dumps(dict(file=target.name), ensure_ascii=False)
    return _run_operation('copy', len(files), str(target), work)


def extract_archive(path):
    """Unpack a ZIP or TAR archive into a new folder next to it, named after the archive."""
    from soovee_commander.providers import ArchiveProvider
    root, archive = local_location(path)
    if not root['writable']: raise ValueError('This storage is read only.')
    name = archive.name
    if not name.lower().endswith(ARCHIVE_SUFFIXES): raise ValueError('This archive type cannot be unpacked on this device.')
    base = next(name[:-len(suffix)] for suffix in ARCHIVE_SUFFIXES if name.lower().endswith(suffix)) or 'Archive'
    target = _free_path(archive.parent, base)
    def work(report):
        provider = ArchiveProvider(str(archive))
        if provider.encrypted: raise ValueError('Password-protected archives cannot be unpacked on this device.')
        target.mkdir()
        try:
            copy_entries(provider, '/', LocalProvider(), str(target), provider.list('/'), operation_cancel, report, conflict='rename')
        except BaseException:
            if not any(target.iterdir()): target.rmdir()
            raise
        logger.info('Native extract completed · %s → %s', path, target.name)
        return json.dumps(dict(folder=target.name), ensure_ascii=False)
    return _run_operation('extract', 1, str(target), work)


def compress_items(paths, name):
    """Pack the selected items of one folder into a new ZIP in that folder."""
    from soovee_commander.packing import create_archive
    items = json.loads(paths)
    if not isinstance(items, list) or not items or any(not isinstance(p, str) for p in items): raise ValueError('Choose files or folders first.')
    locations = [local_location(p) for p in items]
    root, first = locations[0]
    folder = first.parent
    if not root['writable']: raise ValueError('This storage is read only.')
    if any(target.parent != folder or target == Path(r['path']) or _protected(target) for r, target in locations):
        raise ValueError('This storage root or protected folder cannot be copied or moved.')
    name = safe_name(name if name.lower().endswith('.zip') else name + '.zip')
    target = _free_path(folder, name)
    provider = LocalProvider()
    wanted = {target.name for _, target in locations}
    entries = [entry for entry in provider.list(str(folder)) if entry.name in wanted]
    def work(report):
        create_archive(provider, str(folder), str(target), entries, operation_cancel, report, 'zip')
        logger.info('Native compress completed · %d items → %s', len(entries), target.name)
        return json.dumps(dict(file=target.name), ensure_ascii=False)
    return _run_operation('compress', len(entries), str(target), work)


def search_local(path, query, limit=1000):
    """Names containing query anywhere below a local folder. Reads names and metadata only, never contents,
    so files kept only in iCloud are not downloaded."""
    query = str(query).strip().casefold()
    if not query: raise ValueError('Type part of a file name.')
    root, base = local_location(path)
    results, pending, deadline = [], [base], time.monotonic() + 20
    while pending and len(results) < int(limit) and time.monotonic() < deadline:
        folder = pending.pop()
        try:
            with os.scandir(folder) as items:
                for item in items:
                    if item.is_symlink(): continue
                    directory = item.is_dir(follow_symlinks=False)
                    full = Path(item.path)
                    if directory:
                        if _protected(full) or full.name.startswith('.'): continue
                        pending.append(full)
                    if query in item.name.casefold():
                        try: info = item.stat(follow_symlinks=False); size, modified = (0 if directory else info.st_size), info.st_mtime
                        except OSError: size, modified = 0, 0
                        results.append(dict(name=str(full.relative_to(base)).replace(os.sep, '/'), directory=directory, bytes=size, modified=modified))
                        if len(results) >= int(limit): break
        except OSError:
            continue
    return json.dumps(dict(results=results, complete=not pending), ensure_ascii=False)


def cancel_operation():
    """Called on an independent native queue so a running copy can be stopped."""
    operation_cancel.set()
    return json.dumps(operation_state)


def operation_snapshot():
    return json.dumps(operation_state, ensure_ascii=False)


def transfer_items(source_peer, sources, destination_peer, destination, moving=False):
    """Copy selected items to an explicitly chosen folder. Never silently overwrite."""
    global operation_state
    paths = json.loads(sources)
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise ValueError('Choose files or folders first.')
    if moving and (source_peer or destination_peer):
        raise ValueError('Moving between devices is not available yet. Copy, verify, then delete the originals.')
    with operation_lock:
        operation_cancel.clear()
        operation_state = dict(status='running', action='move' if moving else 'copy', files=len(paths), completed=0, bytes=0, destination=destination)
        last_report=[0.0]
        def report(message, count):
            operation_state['bytes'] += count
            if message.startswith('@transfer:'):
                detail=json.loads(message[len('@transfer:'):])
                if detail.get('event')=='file': operation_state['current']=detail.get('source','')
                elif detail.get('event')=='plan':   # totals let the phone show a percentage and time left
                    operation_state['total']=operation_state.get('total',0)+int(detail.get('bytes') or 0)
                    operation_state['total_files']=operation_state.get('total_files',0)+int(detail.get('files') or 0)
            else: operation_state['message']=message
            now=time.monotonic()
            if now-last_report[0]>.1 or count and operation_state['bytes']==count:
                last_report[0]=now
                callbacks.activity(json.dumps(dict(kind='operation', **operation_state), ensure_ascii=False))
        try:
            target_provider=DeviceProvider(service,destination_peer) if destination_peer else LocalProvider()
            if destination_peer:
                if destination=='/': raise ValueError('Choose a shared folder first.')
                target=destination
            else:
                root,target=local_location(destination)
                if not root['writable']: raise ValueError('This storage is read only.')
                target=str(target)
            for path in paths:
                if operation_cancel.is_set():
                    from soovee_commander.operations import Cancelled
                    raise Cancelled('Transfer canceled. Completed files remain at the destination.')
                source_provider=DeviceProvider(service,source_peer) if source_peer else LocalProvider()
                if source_peer:
                    if len(path.strip('/').split('/'))<2: raise ValueError('Choose an item inside a shared folder.')
                    original=path
                    if source_peer==destination_peer and (target==original or target.startswith(original.rstrip('/')+'/')):
                        raise ValueError('Cannot copy a folder into itself or a subfolder.')
                else:
                    root,original=local_location(path)
                    if original==Path(root['path']) or any(original==blocked or original in blocked.parents for blocked in [service.store.directory.resolve(),*service.shares.denied_paths]):
                        raise ValueError('This storage root or protected folder cannot be copied or moved.')
                    if moving and not root['writable']: raise ValueError('This storage is read only.')
                    original=str(original)
                name=PurePosixPath(original).name if source_peer else Path(original).name  # Local paths use OS separators.
                entry=next(e for e in source_provider.list(source_provider.parent(original)) if e.name==name)
                if moving:
                    from soovee_commander.operations import move_local
                    move_local(source_provider,source_provider.parent(original),target_provider,target,[entry],operation_cancel,report)
                # Phones offer no conflict dialog: keep the existing item and give the copy a free name, as Finder does.
                else: copy_entries(source_provider,source_provider.parent(original),target_provider,target,[entry],operation_cancel,report,conflict='rename')
                operation_state['completed']+=1
            operation_state['status']='done'
        except Exception as error:
            operation_state.update(status='canceled' if operation_cancel.is_set() else 'error',message=str(error))
            logger.exception('Native transfer failed')
            raise
        finally:
            callbacks.activity(json.dumps(dict(kind='operation',**operation_state),ensure_ascii=False))
    return snapshot()


def browse(peer='', path='/'):
    provider = DeviceProvider(service, peer) if peer else LocalProvider()
    base = path if peer else str(shared / path.lstrip('/'))
    if not peer and not Path(base).resolve().is_relative_to(shared.resolve()):
        raise ValueError('The path is outside the shared folder.')
    entries = sorted(provider.list(base), key=lambda item: (not item.is_dir, item.name.casefold()))
    return json.dumps([dict(name=e.name, directory=e.is_dir, bytes=e.size, modified=e.modified) for e in entries], ensure_ascii=False)


def download(peer, path):
    provider = DeviceProvider(service, peer)
    entry = next(e for e in provider.list(provider.parent(path)) if e.name == path.rsplit('/', 1)[-1])
    copy_entries(provider, provider.parent(path), LocalProvider(), str(shared), [entry], Event())
    return str(shared / entry.name)


def upload(peer, destination, name):
    safe_name(name)
    local = LocalProvider()
    entry = next(e for e in local.list(str(shared)) if e.name == name)
    copy_entries(local, str(shared), DeviceProvider(service, peer), destination, [entry], Event())
    return snapshot()


def delete_local(path):
    target = shared / path.lstrip('/')
    if target == shared or not target.resolve().is_relative_to(shared.resolve()):
        raise ValueError('The path is outside the shared folder.')
    local = LocalProvider()
    entry = next(e for e in local.list(str(target.parent)) if e.name == target.name)
    local.remove(str(target), entry)
    return snapshot()


def remove_pairing(identity):
    """Forget a paired device: its key, its access to shared folders and open connections. Files stay."""
    service.remove_peer(identity)
    not_recognized.discard(identity)
    return snapshot()


def request_pairing(host, port):
    """Ask a nearby device to show its pairing code; the code is then typed or scanned here.

    Never raises: an older or busy device simply did not show a code, and the
    user can still type the code it displays.
    """
    try:
        response = service.request_pairing(host, int(port))
        return json.dumps(dict(asked=True, name=response.get('name', ''), expires=response.get('expires', 0)), ensure_ascii=False)
    except Exception as exc:
        logger.info('Pairing request not answered: %s', exc)
        return json.dumps(dict(asked=False), ensure_ascii=False)


def import_file(name, descriptor):
    safe_name(name)
    fd, temporary = tempfile.mkstemp(prefix='.soovee-import-', dir=shared)
    try:
        with os.fdopen(fd, 'wb') as output, os.fdopen(os.dup(descriptor), 'rb') as source:
            shutil.copyfileobj(source, output, 256 * 1024)
            output.flush(); os.fsync(output.fileno())
        destination = shared / name
        if not rename_no_replace(temporary, destination):
            os.link(temporary, destination)
            os.unlink(temporary)
        return str(destination)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def stop(owner=None):
    global service
    with lifecycle_lock:
        # A replaced Android Activity must not stop the new Activity's listener.
        if owner is not None and owner != callbacks:
            return
        if service is not None:
            service.stop(); service = None


def diagnostics():
    from soovee_commander.diagnostic_log import read_tail
    return read_tail(60000)


def record_error(message):
    logger.error('Native operation failed: %s', str(message))
