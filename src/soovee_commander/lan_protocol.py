"""Bounded wire framing and TLS 1.3 authentication for local Soovee transfers."""
import base64
import hashlib
import ipaddress
import json
import secrets
import socket
import ssl
import struct
import time
from urllib.parse import urlencode, urlsplit, parse_qs

from .hkdf import hkdf_sha256

VERSION = 1
MAX_MESSAGE = 8 * 1024 * 1024
CHUNK = 256 * 1024


class TransferError(Exception):
    pass


class PairingNotRecognized(TransferError):
    """The other device refused the saved key: it removed or replaced this pairing."""

    def __init__(self):
        super().__init__('The other device no longer recognizes this pairing. Remove it here and pair again.')


def client_tls(sock, key, identity):
    """Open the client side of a paired connection.

    A device that forgot the pairing answers in plain text, which TLS reports as
    a cryptic error such as WRONG_VERSION_NUMBER; a different key fails the
    handshake. Both mean the same thing to the user: pair again.
    """
    try:
        return encrypted_socket(sock, key, identity)
    except (ssl.SSLError, ConnectionError) as exc:   # reset on macOS/Linux, aborted on Windows
        raise PairingNotRecognized() from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def receive_exact(sock, size, cancel=None):
    data = bytearray()
    previous = sock.gettimeout() if cancel is not None else None
    deadline = time.monotonic() + previous if previous is not None else None
    if cancel is not None:
        sock.settimeout(min(previous, .2) if previous is not None else .2)
    try:
        while len(data) < size:
            if cancel is not None and cancel.is_set():
                from .operations import Cancelled
                raise Cancelled('Transfer canceled. Partial data can be resumed after approval.')
            try:
                block = sock.recv(min(CHUNK, size - len(data)))
            except socket.timeout:
                if cancel is None or (deadline is not None and time.monotonic() >= deadline):
                    raise
                continue
            if not block:
                raise TransferError('The connection was interrupted. Retry to resume the transfer.')
            data.extend(block)
    finally:
        if cancel is not None:
            sock.settimeout(previous)
    return bytes(data)


def send_message(sock, message):
    data = canonical(message)
    if len(data) > MAX_MESSAGE:
        raise TransferError('The transfer description is too large.')
    sock.sendall(struct.pack('!I', len(data)) + data)


def receive_message(sock, cancel=None):
    size = struct.unpack('!I', receive_exact(sock, 4, cancel))[0]
    if not 1 <= size <= MAX_MESSAGE:
        raise TransferError('Invalid transfer message size.')
    try:
        result = json.loads(receive_exact(sock, size, cancel))
    except (ValueError, UnicodeError) as exc:
        raise TransferError('Invalid transfer message.') from exc
    if not isinstance(result, dict):
        raise TransferError('Invalid transfer message.')
    if result.get('error'):
        raise TransferError(str(result['error'])[:500])
    return result


def derive_key(key, purpose):
    return hkdf_sha256(key, 32, info=b'soovee.transfer.v1/' + purpose)


def require_tls_psk():
    if not getattr(ssl, 'HAS_PSK', False) or not hasattr(ssl.SSLContext, 'set_psk_client_callback'):
        try:
            from .openssl_psk import require_available
            require_available()
        except (OSError, AttributeError) as exc:
            raise TransferError('This build has no supported TLS 1.3 PSK backend. Use the packaged application.') from exc


def encrypted_socket(sock, key, identity, *, server=False):
    require_tls_psk()
    if not getattr(ssl, 'HAS_PSK', False) or not hasattr(ssl.SSLContext, 'set_psk_client_callback'):
        from .openssl_psk import encrypted_socket as compatible_socket
        return compatible_socket(sock, key, identity, server=server)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    if server:
        # No certificate fallback: an unknown identity or key must fail the handshake.
        context.set_psk_server_callback(lambda claimed: key if secrets.compare_digest(claimed or '', identity) else b'')
    else:
        context.check_hostname = False
        # CERT_REQUIRED also prevents an attacker from replacing PSK with an untrusted certificate.
        context.verify_mode = ssl.CERT_REQUIRED
        context.set_psk_client_callback(lambda hint: (identity, key))
    encrypted = context.wrap_socket(sock, server_side=server, server_hostname=None if server else 'soovee')
    if encrypted.version() != 'TLSv1.3' or not encrypted.session_reused:
        encrypted.close()
        raise TransferError('The authenticated TLS handshake failed.')
    return encrypted


def local_address(host):
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise TransferError('Enter a local IP address, not a public server or hostname.') from exc
    if address.is_unspecified or address.is_multicast or not (address.is_private or address.is_loopback or address.is_link_local):
        raise TransferError('Soovee Transfers currently supports local network addresses only.')
    return str(address)


def invitation(host, port, code):
    return 'soovee-transfer://pair?' + urlencode(dict(v=VERSION, host=local_address(host), port=port, code=code))


def parse_invitation(text):
    url = urlsplit(text.strip())
    if url.scheme != 'soovee-transfer' or url.netloc != 'pair' or url.path or url.fragment or len(text) > 1000:
        raise TransferError('This is not a Soovee pairing invitation.')
    values = parse_qs(url.query, strict_parsing=True)
    if set(values) != {'v', 'host', 'port', 'code'} or any(len(value) != 1 for value in values.values()):
        raise TransferError('Invalid pairing invitation.')
    if values['v'][0] != str(VERSION):
        raise TransferError('The pairing invitation uses an unsupported version.')
    host, port, code = local_address(values['host'][0]), int(values['port'][0]), values['code'][0]
    if not 1 <= port <= 65535 or len(code) != 8 or not code.isascii() or not code.isdigit():
        raise TransferError('Invalid pairing invitation.')
    return host, port, code


def key_text(key):
    return base64.b64encode(key).decode('ascii')


def key_bytes(text):
    value = base64.b64decode(text, validate=True)
    if len(value) != 32:
        raise TransferError('Invalid stored device key.')
    return value


def key_fingerprint(key):
    return hashlib.sha256(key).hexdigest()[:16].upper()
