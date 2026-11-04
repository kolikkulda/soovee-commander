"""Wire compatibility and failure tests for the legacy Android TLS adapter."""
from concurrent.futures import ThreadPoolExecutor
import secrets
import socket
import ssl
from threading import Event, Thread
import time

import pytest

from soovee_commander import openssl_psk as compatibility
from soovee_commander.lan_protocol import encrypted_socket as native, receive_exact, receive_message, send_message


@pytest.fixture(autouse=True)
def supported():
    try:
        compatibility.require_available()
    except (OSError, AttributeError):
        pytest.skip('The host does not export the public OpenSSL PSK API.')


@pytest.mark.parametrize('client,server', [(compatibility.encrypted_socket, native),
    (native, compatibility.encrypted_socket), (compatibility.encrypted_socket, compatibility.encrypted_socket)])
def test_native_and_legacy_exchange_large_binary_frames(client, server):
    a, b = socket.socketpair(); a.settimeout(5); b.settimeout(5)
    key = secrets.token_bytes(32)
    payload = bytes(range(256)) * 7000
    def receive():
        with server(b, key, 'paired-device', server=True) as secure:
            assert secure.version() == 'TLSv1.3' and secure.session_reused
            assert receive_message(secure) == {'size': len(payload)}
            assert receive_exact(secure, len(payload)) == payload
            secure.sendall(payload)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(receive)
        with client(a, key, 'paired-device') as secure:
            send_message(secure, {'size': len(payload)})
            secure.sendall(payload)
            assert receive_exact(secure, len(payload)) == payload
        future.result(timeout=8)


@pytest.mark.parametrize('wrong_identity', [False, True])
@pytest.mark.parametrize('client,server', [(compatibility.encrypted_socket, native), (native, compatibility.encrypted_socket)])
def test_wrong_key_or_identity_cannot_complete_handshake(client, server, wrong_identity):
    a, b = socket.socketpair(); a.settimeout(2); b.settimeout(2)
    key = secrets.token_bytes(32)
    def receive():
        try:
            with pytest.raises((ssl.SSLError, OSError)):
                server(b, key, 'expected', server=True)
        finally: b.close()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(receive)
        try:
            with pytest.raises((ssl.SSLError, OSError)):
                client(a, key if wrong_identity else secrets.token_bytes(32), 'wrong' if wrong_identity else 'expected')
        finally: a.close()
        future.result(timeout=5)


class WireSocket:
    def __init__(self, raw):
        self.raw, self.fragment, self.corrupt = raw, False, False
        self.partial, self.release = Event(), Event()

    def __getattr__(self, name): return getattr(self.raw, name)

    def sendall(self, data):
        if self.corrupt:
            data = data[:-1] + bytes([data[-1] ^ 1])
        if self.fragment:
            self.fragment = False
            self.raw.sendall(data[:5]); self.partial.set()
            assert self.release.wait(3)
            self.raw.sendall(data[5:])
        else:
            self.raw.sendall(data)


def test_partial_tls_records_survive_read_timeout():
    a, b = socket.socketpair(); a.settimeout(2); b.settimeout(2)
    key, wire = secrets.token_bytes(32), WireSocket(b)
    def receive():
        with compatibility.encrypted_socket(wire, key, 'id', server=True) as secure:
            wire.fragment = True
            secure.sendall(b'resumed')
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(receive)
        with compatibility.encrypted_socket(a, key, 'id') as secure:
            assert wire.partial.wait(2)
            secure.settimeout(.04)
            with pytest.raises(socket.timeout): secure.recv(10)
            assert secure.gettimeout() == .04
            wire.release.set(); secure.settimeout(2)
            assert receive_exact(secure, 7, Event()) == b'resumed'
        future.result(timeout=5)


def test_modified_ciphertext_is_rejected():
    a, b = socket.socketpair(); a.settimeout(2); b.settimeout(2)
    key, wire = secrets.token_bytes(32), WireSocket(a)
    def receive():
        with native(b, key, 'id', server=True) as secure:
            with pytest.raises(ssl.SSLError): secure.recv(100)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(receive)
        with compatibility.encrypted_socket(wire, key, 'id') as secure:
            wire.corrupt = True; secure.sendall(b'authenticated payload')
            with pytest.raises(ssl.SSLError): secure.recv(100)
        future.result(timeout=5)


@pytest.mark.parametrize('version', [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_certificate_handshake_cannot_replace_psk(tmp_path, version):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from datetime import datetime, timedelta, timezone
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'untrusted-test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
    pem = tmp_path / 'certificate.pem'
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = version
    context.load_cert_chain(pem)
    a, b = socket.socketpair(); a.settimeout(2); b.settimeout(2)
    def receive():
        try:
            with pytest.raises(ssl.SSLError): context.wrap_socket(b, server_side=True)
        finally: b.close()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(receive)
        try:
            with pytest.raises(ssl.SSLError): compatibility.encrypted_socket(a, secrets.token_bytes(32), 'id')
        finally: a.close()
        future.result(timeout=5)


def test_handshake_timeout_and_closed_socket_are_bounded():
    a, b = socket.socketpair(); a.settimeout(.06)
    started = time.monotonic()
    try:
        with pytest.raises(socket.timeout):
            compatibility.encrypted_socket(a, secrets.token_bytes(32), 'id')
        assert time.monotonic() - started < 1
        assert a.fileno() == -1
    finally: a.close(); b.close()


def test_closing_legacy_socket_interrupts_another_threads_blocked_read():
    a, b = socket.socketpair(); a.settimeout(2); b.settimeout(2)
    key, stop = secrets.token_bytes(32), Event()
    def server():
        with native(b, key, 'id', server=True): stop.wait(4)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(server)
        secure = compatibility.encrypted_socket(a, key, 'id')
        secure.settimeout(None)
        finished, errors = Event(), []
        def read():
            try: secure.recv(1)
            except OSError as error: errors.append(error)
            finally: finished.set()
        thread = Thread(target=read); thread.start()
        time.sleep(.03); secure.close()
        assert finished.wait(1) and errors
        thread.join(1); stop.set(); future.result(timeout=3)
