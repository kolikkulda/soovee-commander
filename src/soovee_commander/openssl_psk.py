"""TLS 1.3 PSK through OpenSSL's public C API for older Android Python builds.

Memory BIOs keep Python in charge of socket deadlines and cancellation. This
does not access CPython SSL internals, change the wire protocol, or accept a
certificate in place of the agreed PSK. Native Python PSK support is preferred.
"""
import contextlib
import ctypes as C
from functools import lru_cache
import secrets
import socket
import ssl
from threading import RLock
import time

CLIENT = C.CFUNCTYPE(C.c_uint, C.c_void_p, C.c_char_p, C.c_void_p, C.c_uint, C.c_void_p, C.c_uint)
SERVER = C.CFUNCTYPE(C.c_uint, C.c_void_p, C.c_char_p, C.c_void_p, C.c_uint)
CHUNK = 256 * 1024


@lru_cache(maxsize=1)
def api():
    import _ssl
    library = C.CDLL(_ssl.__file__)
    definitions = {
        'TLS_method': (C.c_void_p, []),
        'SSL_CTX_new': (C.c_void_p, [C.c_void_p]),
        'SSL_CTX_free': (None, [C.c_void_p]),
        'SSL_CTX_ctrl': (C.c_long, [C.c_void_p, C.c_int, C.c_long, C.c_void_p]),
        'SSL_CTX_set_verify': (None, [C.c_void_p, C.c_int, C.c_void_p]),
        'SSL_CTX_set_psk_client_callback': (None, [C.c_void_p, CLIENT]),
        'SSL_CTX_set_psk_server_callback': (None, [C.c_void_p, SERVER]),
        'SSL_new': (C.c_void_p, [C.c_void_p]),
        'SSL_free': (None, [C.c_void_p]),
        'SSL_set_bio': (None, [C.c_void_p, C.c_void_p, C.c_void_p]),
        'SSL_set_accept_state': (None, [C.c_void_p]),
        'SSL_set_connect_state': (None, [C.c_void_p]),
        'SSL_do_handshake': (C.c_int, [C.c_void_p]),
        'SSL_get_error': (C.c_int, [C.c_void_p, C.c_int]),
        'SSL_get_version': (C.c_char_p, [C.c_void_p]),
        'SSL_session_reused': (C.c_int, [C.c_void_p]),
        'SSL_read': (C.c_int, [C.c_void_p, C.c_void_p, C.c_int]),
        'SSL_write': (C.c_int, [C.c_void_p, C.c_void_p, C.c_int]),
        'BIO_s_mem': (C.c_void_p, []),
        'BIO_new': (C.c_void_p, [C.c_void_p]),
        'BIO_free': (C.c_int, [C.c_void_p]),
        'BIO_ctrl_pending': (C.c_size_t, [C.c_void_p]),
        'BIO_read': (C.c_int, [C.c_void_p, C.c_void_p, C.c_int]),
        'BIO_write': (C.c_int, [C.c_void_p, C.c_void_p, C.c_int]),
        'ERR_clear_error': (None, []),
    }
    for name, (result, arguments) in definitions.items():
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments
    return library


def require_available():
    api()


class PSKSocket:
    def __init__(self, raw, key, identity, *, server=False):
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError('A 32-byte transfer key is required.')
        identity = identity.encode('ascii')
        if not identity or len(identity) > 128 or b'\0' in identity:
            raise ValueError('Invalid TLS identity.')
        self.raw, self.lib, self.lock = raw, api(), RLock()
        self.context = self.ssl = None
        self.incoming = self.outgoing = None
        self.closed = False
        try:
            lib = self.lib
            self.context = lib.SSL_CTX_new(lib.TLS_method())
            if not self.context:
                raise ssl.SSLError('Could not create the TLS context.')
            # Public OpenSSL SSL_CTRL_SET_MIN/MAX_PROTO_VERSION constants.
            for command in (123, 124):
                if lib.SSL_CTX_ctrl(self.context, command, 0x0304, None) != 1:
                    raise ssl.SSLError('TLS 1.3 is unavailable.')
            if server:
                def callback(connection, claimed, output, maximum):
                    if maximum < len(key) or not secrets.compare_digest(claimed or b'', identity):
                        return 0
                    C.memmove(output, key, len(key)); return len(key)
                self.callback = SERVER(callback)
                lib.SSL_CTX_set_psk_server_callback(self.context, self.callback)
            else:
                def callback(connection, hint, output_identity, maximum_identity, output_key, maximum_key):
                    if maximum_identity <= len(identity) or maximum_key < len(key):
                        return 0
                    C.memmove(output_identity, identity + b'\0', len(identity) + 1)
                    C.memmove(output_key, key, len(key)); return len(key)
                self.callback = CLIENT(callback)
                lib.SSL_CTX_set_psk_client_callback(self.context, self.callback)
                # No CA roots or verification override: certificate fallback fails.
                lib.SSL_CTX_set_verify(self.context, 1, None)
            self.ssl = lib.SSL_new(self.context)
            if not self.ssl:
                raise ssl.SSLError('Could not create the TLS connection.')
            incoming, outgoing = lib.BIO_new(lib.BIO_s_mem()), lib.BIO_new(lib.BIO_s_mem())
            if not incoming or not outgoing:
                if incoming: lib.BIO_free(incoming)
                if outgoing: lib.BIO_free(outgoing)
                raise MemoryError('Could not allocate TLS buffers.')
            self.incoming, self.outgoing = incoming, outgoing
            lib.SSL_set_bio(self.ssl, incoming, outgoing)  # SSL owns both BIOs.
            (lib.SSL_set_accept_state if server else lib.SSL_set_connect_state)(self.ssl)
            self._operate(lib.SSL_do_handshake, (), self._deadline())
            if self.version() != 'TLSv1.3' or not self.session_reused:
                raise ssl.SSLError('The authenticated TLS handshake failed.')
        except BaseException:
            self.close()
            raise

    def _deadline(self):
        timeout = self.gettimeout()
        if timeout == 0:
            raise ValueError('Nonblocking TLS sockets are not supported.')
        return time.monotonic() + timeout if timeout is not None else None

    def _network(self, function, value, deadline):
        previous = self.raw.gettimeout()
        try:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise socket.timeout('The TLS operation timed out.')
                self.raw.settimeout(remaining)
            return function(value)
        finally:
            with contextlib.suppress(OSError): self.raw.settimeout(previous)

    def _flush(self, deadline):
        while self.lib.BIO_ctrl_pending(self.outgoing):
            buffer = C.create_string_buffer(min(CHUNK, self.lib.BIO_ctrl_pending(self.outgoing)))
            count = self.lib.BIO_read(self.outgoing, buffer, len(buffer))
            if count <= 0: raise ssl.SSLError('Could not read TLS output.')
            try:
                self._network(self.raw.sendall, buffer.raw[:count], deadline)
            except OSError as exc:
                # A timed-out write may have sent only part of a TLS record.
                # It must abort the connection, never be retried as a read timeout.
                raise ssl.SSLError('The TLS output was interrupted.') from exc

    def _operate(self, function, arguments, deadline):
        while True:
            if self.closed: raise OSError('The TLS connection is closed.')
            # SSL_get_error must run immediately, on the same thread, with a
            # previously empty OpenSSL error queue (OpenSSL's documented API).
            self.lib.ERR_clear_error()
            result = function(self.ssl, *arguments)
            error = self.lib.SSL_get_error(self.ssl, result) if result <= 0 else 0
            self._flush(deadline)
            if result > 0: return result
            if error == 6: return 0  # Authenticated close_notify.
            if error == 2:  # SSL_ERROR_WANT_READ
                data = self._network(self.raw.recv, CHUNK, deadline)
                if not data: raise ssl.SSLEOFError('The TLS connection was interrupted.')
                if self.lib.BIO_write(self.incoming, data, len(data)) != len(data):
                    raise ssl.SSLError('Could not buffer TLS input.')
            elif error != 3:  # SSL_ERROR_WANT_WRITE is drained by _flush.
                raise ssl.SSLError('The authenticated TLS operation failed.')

    def recv(self, size):
        if size < 0: raise ValueError('Invalid receive size.')
        if not size: return b''
        with self.lock:
            buffer = C.create_string_buffer(min(size, CHUNK))
            count = self._operate(self.lib.SSL_read, (buffer, len(buffer)), self._deadline())
            return buffer.raw[:count]

    def sendall(self, data):
        with self.lock:
            deadline = self._deadline()
            view = memoryview(data)
            offset = 0
            while offset < len(view):
                block = bytes(view[offset:offset + CHUNK])
                buffer = C.create_string_buffer(block)
                count = self._operate(self.lib.SSL_write, (buffer, len(block)), deadline)
                if not count: raise ssl.SSLError('The TLS connection is closed.')
                offset += count

    def version(self):
        with self.lock:
            return self.lib.SSL_get_version(self.ssl).decode('ascii') if self.ssl else None

    @property
    def session_reused(self):
        with self.lock:
            return bool(self.ssl and self.lib.SSL_session_reused(self.ssl))

    def settimeout(self, value): self.raw.settimeout(value)
    def gettimeout(self): return self.raw.gettimeout()
    def fileno(self): return self.raw.fileno()
    def shutdown(self, how): self.raw.shutdown(how)

    def close(self):
        # Interrupt another thread's blocking recv before waiting for its lock.
        with contextlib.suppress(OSError): self.raw.shutdown(socket.SHUT_RDWR)
        with self.lock:
            if self.closed: return
            self.closed = True
            if self.ssl: self.lib.SSL_free(self.ssl); self.ssl = None
            if self.context: self.lib.SSL_CTX_free(self.context); self.context = None
            self.callback = None
            self.raw.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def encrypted_socket(raw, key, identity, *, server=False):
    return PSKSocket(raw, key, identity, server=server)
