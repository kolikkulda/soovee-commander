"""Opt-in local transfer service: SPAKE2 pairing, TLS 1.3 PSK and explicit offers."""
import contextlib
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import ssl
from threading import Event, Lock, RLock, Semaphore, Thread
import time

from spake2 import SPAKE2_A, SPAKE2_B

from .lan_files import ReceiveBundle, check, plan_sources, signature, stream_hash, validate_manifest
from .lan_protocol import (CHUNK, VERSION, TransferError, client_tls, derive_key, encrypted_socket, invitation,
                           local_address, receive_message, require_tls_psk, send_message)
from .lan_store import DeviceStore, Peer, valid_id, valid_name
from .transfer_status import emit as progress_event
from .operations import Cancelled


class TransferService:
    """No listener starts until start() is explicitly called. Default bind is loopback."""
    def __init__(self, state_directory, name=None, *, approve_pair=lambda peer: False,
                 approve_offer=lambda peer, manifest, cancel: None, event=lambda value: None, device_kind="desktop"):
        self.store = DeviceStore(state_directory, name)
        from .device_files import SharedFolders
        self.shares = SharedFolders(self.store.directory, device_kind)
        self.approve_pair, self.approve_offer, self.event = approve_pair, approve_offer, event
        self.stopping = Event()
        self.listener = None
        self.port = 0
        self.lock = RLock()
        self.pair_lock = Lock()
        self.slots = Semaphore(4)
        self.receive_slot = Semaphore(1)
        self.sockets = {}
        self.workers = set()
        self.offers = set()
        self.receiving_cancels = {}
        self.outgoing_cancels = {}
        self.pairing = None
        self.last_pair_request = 0.0
        self.pair_requests_by_host = {}
        try:
            stored = json.loads((self.store.directory / 'pairing.json').read_text(encoding='utf-8'))
            self.accept_pair_requests = stored.get('requests', True) is not False
        except (OSError, ValueError, AttributeError):
            self.accept_pair_requests = True
        self.last_progress = {}

    def start(self, host='127.0.0.1', port=0):
        require_tls_psk()
        if self.listener is not None:
            return self.port
        address = ipaddress.ip_address(host)
        if not address.is_unspecified:
            local_address(host)
        listener = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            elif os.name != 'nt':
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, port))
            listener.listen(8)
            listener.settimeout(.25)
        except BaseException:
            listener.close()
            raise
        self.listener = listener
        self.port = listener.getsockname()[1]
        self.stopping.clear()
        self.thread = Thread(target=self._accept, name='Soovee listener', daemon=True)
        self.thread.start()
        return self.port

    def begin_pairing(self, *, lifetime=300):
        if self.listener is None:
            raise TransferError('Enable Soovee Transfers first.')
        with self.lock:
            self.pairing = dict(code=f'{secrets.randbelow(100000000):08d}', id=secrets.token_hex(16),
                                expires=time.monotonic() + lifetime, attempts=0)
            return self.pairing['code']

    def pairing_link(self, host):
        with self.lock:
            if self.pairing is None or time.monotonic() >= self.pairing['expires']:
                raise TransferError('The pairing code has expired. Generate a new code.')
            return invitation(host, self.port, self.pairing['code'])

    def cancel_pairing(self):
        with self.lock:
            self.pairing = None

    def _event(self, kind, **values):
        identity = values.get('transfer', '')
        if kind == 'progress':
            now = time.monotonic()
            if now - self.last_progress.get(identity, 0) < .1:
                return
            self.last_progress[identity] = now
        try:
            self.event(dict(kind=kind, **values))
        except Exception:
            # A closed UI must not change transfer authorization or publish status.
            pass

    def _track(self, sock, peer_id=''):
        with self.lock:
            self.sockets[sock] = peer_id
        return sock

    def _accept(self):
        while not self.stopping.is_set():
            try:
                connection, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                local_address(address[0])
            except TransferError:
                connection.close()
                continue
            if not self.slots.acquire(blocking=False):
                connection.close()
                continue
            connection.settimeout(30)
            self._track(connection)
            worker = Thread(target=self._handle, args=(connection, address[0]), daemon=True, name='Soovee request')
            with self.lock:
                self.workers.add(worker)
            worker.start()

    def _handle(self, connection, host):
        import threading
        secure = None
        try:
            request = receive_message(connection)
            if request.get('version') != VERSION:
                raise TransferError('Unsupported Soovee transfer protocol version.')
            if request.get('operation') == 'pair':
                secure = self._receive_pair(connection, host, request)
            elif request.get('operation') == 'pair-request':
                self._receive_pair_request(connection, host, request)
            elif request.get('operation') in ('transfer', 'files'):
                peer = self.store.get(valid_id(request.get('device')))
                secure = self._track(encrypted_socket(connection, peer.secret, peer.id, server=True), peer.id)
                if request['operation'] == 'files':
                    from .device_files import handle_files
                    handle_files(self, secure, peer)
                else:
                    self._receive_offer(secure, peer)
            else:
                raise TransferError('Unknown transfer operation.')
        except Exception as exc:
            # Before TLS, only generic protocol errors are returned. Never echo a key or code.
            target = secure or connection
            with contextlib.suppress(Exception):
                send_message(target, dict(error=str(exc)[:500] if secure is not None and isinstance(exc, (TransferError, Cancelled)) else 'The transfer could not be completed. Check the receiving device.'))
            self._event('error', message=str(exc)[:500])
        finally:
            for sock in (secure, connection):
                if sock is not None:
                    with self.lock:
                        self.sockets.pop(sock, None)
                    with contextlib.suppress(OSError):
                        sock.close()
            with self.lock:
                self.workers.discard(threading.current_thread())
            self.slots.release()

    def _store_paired(self, peer):
        """Save a newly approved pairing.

        If one side forgot an earlier pairing, a new code-verified and approved
        pairing replaces the old key. Folder grants made under the old key end,
        so a device can never inherit access it was not given in this pairing.
        """
        old = next((value for value in self.store.peers() if value.id == peer.id), None)
        if old is not None and old.secret != peer.secret:
            self.store.remove(peer.id)
            self.shares.revoke_peer(peer.id)
        self.store.add(peer)

    def set_pair_requests(self, enabled):
        """Allow or refuse nearby devices asking this one to show its pairing code."""
        from .lan_store import atomic_json
        self.accept_pair_requests = bool(enabled)
        atomic_json(self.store.directory / 'pairing.json', dict(requests=self.accept_pair_requests))

    # One request per address every 10 s and at most 5 per address in 10 minutes,
    # so a device on the network cannot keep popping up the pairing screen.
    PAIR_REQUEST_GAP, PAIR_REQUEST_WINDOW, PAIR_REQUEST_LIMIT = 10.0, 600.0, 5

    def _receive_pair_request(self, connection, host, request):
        """Another device asks this one to show its pairing code.

        Nothing secret travels: the code is only displayed here and typed (or
        scanned) on the asking device, and the SPAKE2 pairing that follows
        still needs explicit approval on both sides. Requests are rate limited
        per address and can be turned off.
        """
        if not self.accept_pair_requests:
            raise TransferError('This device does not accept pairing requests.')
        name = valid_name(request.get('name') or 'Device')
        with self.lock:
            now = time.monotonic()
            recent = [value for value in self.pair_requests_by_host.get(host, []) if now - value < self.PAIR_REQUEST_WINDOW]
            if now - self.last_pair_request < 2 or recent and now - recent[-1] < self.PAIR_REQUEST_GAP or len(recent) >= self.PAIR_REQUEST_LIMIT:
                raise TransferError('Wait a moment before asking again.')
            self.last_pair_request = now
            self.pair_requests_by_host = {key: [value for value in values if now - value < self.PAIR_REQUEST_WINDOW]
                                          for key, values in self.pair_requests_by_host.items() if key != host}
            self.pair_requests_by_host = dict(list(self.pair_requests_by_host.items())[-255:])
            self.pair_requests_by_host[host] = recent + [now]
            session = self.pairing
            if session is None or now >= session['expires'] or session['attempts'] >= 5:
                self.begin_pairing()
            remaining = int(self.pairing['expires'] - now)
        send_message(connection, dict(showing=True, expires=remaining, name=self.store.name))
        self._event('pair-request', name=name, host=host)

    def request_pairing(self, host, port):
        """Ask a nearby device to display its pairing code for this device."""
        host = local_address(host)
        if self.listener is None:
            raise TransferError('Enable Soovee Transfers first.')
        with socket.create_connection((host, int(port)), timeout=10) as connection:
            self._track(connection)
            try:
                send_message(connection, dict(version=VERSION, operation='pair-request', id=self.store.id, name=self.store.name))
                response = receive_message(connection)
            finally:
                with self.lock:
                    self.sockets.pop(connection, None)
        if not response.get('showing'):
            raise TransferError('The other device could not show a pairing code. Open Soovee there and try again.')
        return response

    def _receive_pair(self, connection, host, request):
        if not self.pair_lock.acquire(blocking=False):
            raise TransferError('Another pairing is in progress.')
        secure = None
        try:
            with self.lock:
                session = self.pairing
                if not session or self.stopping.is_set() or time.monotonic() >= session['expires'] or session['attempts'] >= 5:
                    raise TransferError('Pairing is unavailable or the code has expired. Generate a new code.')
                session['attempts'] += 1
            # Each attempt uses fresh SPAKE2 state; the short code is not sent on the network.
            public = bytes.fromhex(request['public'])
            if len(public) != 33:
                raise TransferError('Invalid pairing message.')
            exchange = SPAKE2_B(session['code'].encode('ascii'), idA=b'soovee.sender.v1', idB=b'soovee.receiver.v1')
            send_message(connection, dict(public=exchange.start().hex(), session=session['id']))
            shared = exchange.finish(public)
            secure = self._track(encrypted_socket(connection, derive_key(shared, b'pairing'), session['id'], server=True))
            secure.settimeout(150)
            hello = receive_message(secure)
            peer = Peer(valid_id(hello['id']), valid_name(hello['name']), host, hello['port'], derive_key(shared, b'trust'))
            if peer.id == self.store.id:
                raise TransferError('A device cannot pair with itself.')
            send_message(secure, dict(id=self.store.id, name=self.store.name, port=self.port))
            confirmation = receive_message(secure)
            if confirmation != {'accept': True} or not self.approve_pair(peer):
                raise TransferError('Pairing was declined.')
            with self.lock:
                if self.stopping.is_set() or self.pairing is not session or time.monotonic() >= session['expires']:
                    raise TransferError('The pairing code expired or was canceled.')
                self._store_paired(peer)
                self.pairing = None
            send_message(secure, dict(paired=True))
            self._event('paired', device=peer.id, name=peer.name)
            return secure
        except Exception as exc:
            if secure is not None:
                with contextlib.suppress(Exception):
                    send_message(secure, dict(error=str(exc)[:500] if isinstance(exc, TransferError) else 'Pairing failed.'))
            raise
        finally:
            self.pair_lock.release()
            # _handle cannot own an upgraded socket when a handshake callback fails.
            if secure is not None:
                with self.lock:
                    self.sockets.pop(secure, None)
                secure.close()

    def pair(self, host, port, code, *, approve=lambda peer: False):
        require_tls_psk()
        host = local_address(host)
        if self.listener is None:
            raise TransferError('Enable Soovee Transfers first.')
        if not isinstance(code, str) or len(code) != 8 or not code.isascii() or not code.isdigit():
            raise TransferError('Enter the eight-digit pairing code.')
        exchange = SPAKE2_A(code.encode('ascii'), idA=b'soovee.sender.v1', idB=b'soovee.receiver.v1')
        with socket.create_connection((host, int(port)), timeout=30) as connection:
            self._track(connection)
            secure = None
            try:
                send_message(connection, dict(version=VERSION, operation='pair', public=exchange.start().hex()))
                response = receive_message(connection)
                public, session = bytes.fromhex(response['public']), response['session']
                valid_id(session)
                if len(public) != 33:
                    raise TransferError('Invalid pairing message.')
                shared = exchange.finish(public)
                secure = self._track(encrypted_socket(connection, derive_key(shared, b'pairing'), session))
                secure.settimeout(150)
                send_message(secure, dict(id=self.store.id, name=self.store.name, port=self.port))
                hello = receive_message(secure)
                peer = Peer(valid_id(hello['id']), valid_name(hello['name']), host, hello['port'], derive_key(shared, b'trust'))
                if peer.id == self.store.id or not approve(peer):
                    send_message(secure, dict(accept=False))
                    raise TransferError('Pairing was declined.')
                send_message(secure, dict(accept=True))
                if receive_message(secure) != {'paired': True}:
                    raise TransferError('The other device did not confirm pairing.')
                self._store_paired(peer)
                self._event('paired', device=peer.id, name=peer.name)
                return peer
            except ssl.SSLError as exc:
                raise TransferError('Pairing failed. Check the code and generate a new one if needed.') from exc
            finally:
                for sock in (secure, connection):
                    if sock is not None:
                        with self.lock:
                            self.sockets.pop(sock, None)
                        sock.close()

    def send(self, peer_id, paths, cancel=None, report=lambda *args: None, *, plan=None):
        cancel = cancel or Event()
        with self.lock:
            self.outgoing_cancels[cancel] = peer_id
        try:
            return self._send(peer_id, paths, cancel, report, plan=plan)
        finally:
            with self.lock:
                self.outgoing_cancels.pop(cancel, None)

    def _send(self, peer_id, paths, cancel=None, report=lambda *args: None, *, plan=None):
        cancel = cancel or Event()
        if self.stopping.is_set():
            raise TransferError('Local transfers are disabled.')
        plan = plan or plan_sources(paths, cancel, report)
        peer = self.store.get(peer_id)
        total = validate_manifest(plan.manifest)
        files = [item for item in plan.manifest['items'] if item['kind'] == 'file']
        check(cancel)
        for item in files:
            with plan.open(item):
                pass
        progress_event(report, 'plan', bytes=total, files=len(files))
        with socket.create_connection((peer.host, peer.port), timeout=30) as connection:
            self._track(connection, peer.id)
            secure = None
            try:
                send_message(connection, dict(version=VERSION, operation='transfer', device=self.store.id))
                secure = self._track(client_tls(connection, peer.secret, self.store.id), peer.id)
                secure.settimeout(150)
                monitor_done = Event()
                def watch_cancel():
                    while not monitor_done.wait(.1):
                        if cancel.is_set() or self.stopping.is_set():
                            with contextlib.suppress(OSError):
                                secure.shutdown(socket.SHUT_RDWR)
                            return
                monitor = Thread(target=watch_cancel, daemon=True, name='Soovee cancellation')
                monitor.start()
                send_message(secure, dict(manifest=plan.manifest))
                report('Waiting for the receiving device to accept the transfer…', 0)
                response = receive_message(secure, cancel)
                if response.get('accepted') is not True:
                    raise TransferError('The receiving device declined the transfer.')
                if response.get('completed') is True:
                    for item in files:
                        progress_event(report, 'skip', path=item['path'], size=item['size'])
                    return response['destination']
                offsets = response.get('offsets')
                if not isinstance(offsets, list) or len(offsets) != len(files):
                    raise TransferError('Invalid resume information.')
                secure.settimeout(30)
                for index, item in enumerate(files):
                    check(cancel)
                    self.store.get(peer.id)
                    offset, prefix = offsets[index]['offset'], offsets[index]['sha256']
                    if type(offset) is not int or not 0 <= offset <= item['size']:
                        raise TransferError('Invalid resume position.')
                    progress_event(report, 'file', source=item['path'], destination=peer.name + '/' + item['path'], size=item['size'])
                    with plan.open(item) as stream:
                        if stream_hash(stream, cancel, offset) != prefix:
                            offset = 0
                            stream.seek(0)
                            report('Partial data differs; restarting: ' + item['path'], 0)
                        send_message(secure, dict(file=index, offset=offset))
                        if offset:
                            progress_event(report, 'resume', offset=offset)
                        transferred = 0
                        while block := stream.read(min(CHUNK, item['size'] - offset - transferred)):
                            check(cancel)
                            self.store.get(peer.id)
                            secure.sendall(block)
                            transferred += len(block)
                            progress_event(report, 'advance', bytes=transferred)
                        if transferred + offset != item['size'] or signature(os.fstat(stream.fileno())) != plan.sources[item['path']][1]:
                            raise TransferError('The source changed during transfer.')
                    if receive_message(secure, cancel) != {'verified': index}:
                        raise TransferError('The receiving device did not verify the file.')
                    progress_event(report, 'file_done', path=item['path'], size=item['size'], transferred=transferred)
                report('Verifying and publishing the received bundle…', 0)
                result = receive_message(secure, cancel)
                while result.get('verifying') is True:
                    check(cancel)
                    result = receive_message(secure, cancel)
                if result.get('completed') is not True:
                    raise TransferError('The receiving device did not complete the transfer.')
                return result['destination']
            except (OSError, TransferError):
                check(cancel)
                raise
            finally:
                if 'monitor_done' in locals():
                    monitor_done.set()
                    monitor.join(timeout=1)
                for sock in (secure, connection):
                    if sock is not None:
                        with self.lock:
                            self.sockets.pop(sock, None)
                        sock.close()

    def _receive_offer(self, secure, peer):
        request = receive_message(secure)
        manifest = request.get('manifest')
        total = validate_manifest(manifest)
        from .lan_protocol import canonical
        identity = hashlib.sha256(canonical(manifest)).hexdigest()
        offer_key = peer.id + identity
        with self.lock:
            if offer_key in self.offers:
                raise TransferError('The same transfer is already running.')
            self.offers.add(offer_key)
        cancel = Event()
        if not self.receive_slot.acquire(blocking=False):
            with self.lock:
                self.offers.discard(offer_key)
            raise TransferError('Another incoming transfer is active. Retry when it finishes.')
        try:
            from PySide6.QtCore import QLockFile
        except ImportError:
            from .lan_store import HeadlessProfileLock as QLockFile
        profile_lock = QLockFile(str(self.store.directory / 'receive.lock'))
        if not profile_lock.tryLock(0):
            self.receive_slot.release()
            with self.lock:
                self.offers.discard(offer_key)
            raise TransferError('Another incoming transfer is active in this profile.')
        with self.lock:
            self.receiving_cancels[cancel] = peer.id
        try:
            self._event('offer', transfer=identity, name=peer.name, total=total)
            destination = self.approve_offer(peer, manifest, cancel)
            self.store.get(peer.id)
            if destination is None or self.stopping.is_set():
                send_message(secure, dict(accepted=False))
                self._event('declined', transfer=identity, name=peer.name)
                return
            bundle = ReceiveBundle(destination, peer.id, manifest, cancel)
            if bundle.already_complete:
                send_message(secure, dict(accepted=True, completed=True, destination=str(bundle.output)))
                self._event('completed', transfer=identity, name=peer.name, destination=str(bundle.output), total=total)
                return
            offsets = [dict(offset=offset, sha256=digest) for offset, digest in (bundle.partial_info(i) for i in range(len(bundle.files)))]
            send_message(secure, dict(accepted=True, offsets=offsets))
            secure.settimeout(30)
            completed = 0
            for index, item in enumerate(bundle.files):
                check(cancel)
                if self.stopping.is_set():
                    raise TransferError('Receiving was stopped.')
                self.store.get(peer.id)
                incoming = receive_message(secure)
                if set(incoming) != {'file', 'offset'} or incoming['file'] != index or type(incoming['offset']) is not int or incoming['offset'] not in (0, offsets[index]['offset']):
                    raise TransferError('Invalid file order or resume request.')
                self._event('file', transfer=identity, name=peer.name, path=item['path'], size=item['size'], total=total)
                bundle.receive_file(index, incoming['offset'], secure,
                                    lambda value: self._event('progress', transfer=identity, name=peer.name, path=item['path'], done=completed + value, total=total))
                completed += item['size']
                send_message(secure, dict(verified=index))
            self._event('verifying', transfer=identity, name=peer.name)
            heartbeat_done = Event()
            def heartbeat():
                while not heartbeat_done.wait(5):
                    try:
                        send_message(secure, dict(verifying=True))
                    except OSError:
                        cancel.set()
                        return
            heartbeat_thread = Thread(target=heartbeat, daemon=True, name='Soovee verification')
            heartbeat_thread.start()
            try:
                result = bundle.publish()
            finally:
                heartbeat_done.set()
                heartbeat_thread.join(timeout=1)
            send_message(secure, dict(completed=True, destination=str(result)))
            self._event('completed', transfer=identity, name=peer.name, destination=str(result), total=total)
        except Exception:
            self._event('interrupted', transfer=identity, name=peer.name)
            raise
        finally:
            with self.lock:
                self.offers.discard(offer_key)
                self.last_progress.pop(identity, None)
                self.receiving_cancels.pop(cancel, None)
            profile_lock.unlock()
            self.receive_slot.release()

    @contextlib.contextmanager
    def files_connection(self, peer_id, *, endpoint=None):
        if self.stopping.is_set() or self.shares.mode == 'controlled':
            raise TransferError('This device is currently in controlled-device mode.')
        peer = self.store.get(peer_id)
        host, port = endpoint if endpoint is not None else (peer.host, peer.port)
        local_address(host)
        if type(port) is not int or not 1 <= port <= 65535:
            raise TransferError('Invalid device port.')
        with socket.create_connection((host, port), timeout=10 if endpoint is not None else 30) as connection:
            self._track(connection, peer_id)
            secure = None
            try:
                send_message(connection, dict(version=VERSION, operation='files', device=self.store.id))
                secure = self._track(client_tls(connection, peer.secret, self.store.id), peer_id)
                yield secure
            finally:
                for sock in (secure, connection):
                    if sock is not None:
                        with self.lock:
                            self.sockets.pop(sock, None)
                        sock.close()

    def remove_peer(self, identity):
        self.store.remove(identity)
        self.shares.revoke_peer(identity)
        with self.lock:
            for cancel, owner in {**self.receiving_cancels, **self.outgoing_cancels}.items():
                if owner == identity:
                    cancel.set()
            sockets = [sock for sock, peer_id in self.sockets.items() if peer_id == identity]
        for sock in sockets:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def stop(self):
        self.stopping.set()
        self.cancel_pairing()
        with self.lock:
            for cancel in list(self.receiving_cancels) + list(self.outgoing_cancels):
                cancel.set()
            sockets = list(self.sockets)
        for sock in sockets:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
        if self.listener is not None:
            self.listener.close()
            self.thread.join(timeout=2)
            self.listener = None
        with self.lock:
            workers = list(self.workers)
        for worker in workers:
            worker.join(timeout=.1)
