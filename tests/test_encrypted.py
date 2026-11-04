"""Real loopback TLS/SSH tests; generated keys stay inside pytest's temp directory."""
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import socket
import ssl
from threading import Event, Thread

import paramiko
import pytest

from soovee_commander.operations import copy_entries, preview
from soovee_commander.providers import Connection, LocalProvider, RemoteProvider


@pytest.fixture
def tls_server(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import TLS_FTPHandler
    from pyftpdlib.servers import FTPServer

    root = tmp_path / "server"
    root.mkdir()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    pem = tmp_path / "server.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM) +
                    key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    ca = tmp_path / "ca.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    authorizer = DummyAuthorizer()
    authorizer.add_user("test", "secret", str(root), perm="elradfmwMT")

    class Handler(TLS_FTPHandler):
        certfile = str(pem)
        tls_control_required = True
        tls_data_required = True

    Handler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", 0), Handler)
    port = server.socket.getsockname()[1]
    stop = Event()

    def serve():
        while not stop.is_set():
            server.serve_forever(timeout=0.01, blocking=False, handle_exit=False)

    thread = Thread(target=serve, daemon=True)
    thread.start()
    yield RemoteProvider(Connection("FTPS", "127.0.0.1", port, "test", "secret")), root, ca
    stop.set()
    thread.join(timeout=2)
    server.close_all()


def test_ftps_verified_tls_upload_download_and_untrusted_certificate(tls_server, tmp_path, monkeypatch):
    remote, root, ca = tls_server
    with pytest.raises(ssl.SSLCertVerificationError):
        remote.list("/")
    create_context = ssl.create_default_context
    monkeypatch.setattr("soovee_commander.providers.ssl.create_default_context",
                        lambda: create_context(cafile=str(ca)))
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    data = b"FTPS verified data\n" * 100_000
    (source / "file.txt").write_bytes(data)
    local = LocalProvider()
    copy_entries(local, str(source), remote, "/", local.list(str(source)), Event())
    assert (root / "file.txt").read_bytes() == data
    copy_entries(remote, "/", local, str(target), remote.list("/"), Event())
    assert (target / "file.txt").read_bytes() == data


@pytest.fixture
def sftp_server(tmp_path, monkeypatch):
    root = tmp_path / "server"
    root.mkdir()
    server_key = paramiko.RSAKey.generate(2048)

    class Auth(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL if (username, password) == ("test", "secret") else paramiko.AUTH_FAILED

        def get_allowed_auths(self, username):
            return "password"

        def check_channel_request(self, kind, channel_id):
            return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    class Files(paramiko.SFTPServerInterface):
        def path(self, value):
            candidate = (root / value.lstrip("/")).resolve()
            if candidate != root and root not in candidate.parents:
                raise PermissionError("Outside test root")
            return candidate

        def list_folder(self, path):
            result = []
            for item in self.path(path).iterdir():
                attr = paramiko.SFTPAttributes.from_stat(item.lstat())
                attr.filename = item.name
                result.append(attr)
            return result

        def stat(self, path):
            try:
                return paramiko.SFTPAttributes.from_stat(self.path(path).stat())
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno)

        lstat = stat

        def open(self, path, flags, attr):
            try:
                descriptor = os.open(self.path(path), flags, 0o600)
                mode = "r+b" if flags & os.O_RDWR else "wb" if flags & os.O_WRONLY else "rb"
                stream = os.fdopen(descriptor, mode)
                handle = paramiko.SFTPHandle(flags)
                handle.readfile = stream
                handle.writefile = stream
                return handle
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno)

        def remove(self, path):
            self.path(path).unlink()
            return paramiko.SFTP_OK

        def mkdir(self, path, attr):
            self.path(path).mkdir()
            return paramiko.SFTP_OK

        def rmdir(self, path):
            self.path(path).rmdir()
            return paramiko.SFTP_OK

        def rename(self, old, new):
            if self.path(new).exists():
                return paramiko.SFTP_FAILURE
            self.path(old).rename(self.path(new))
            return paramiko.SFTP_OK

        def posix_rename(self, old, new):
            os.replace(self.path(old), self.path(new))
            return paramiko.SFTP_OK

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    port = listener.getsockname()[1]
    stop = Event()
    transports = []

    def serve():
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            transport = paramiko.Transport(client)
            transports.append(transport)
            transport.add_server_key(server_key)
            transport.set_subsystem_handler("sftp", paramiko.SFTPServer, Files)
            try:
                transport.start_server(server=Auth())
            except (paramiko.SSHException, EOFError, OSError):
                transport.close()

    def known_hosts(client):
        client.get_host_keys().add(f"[127.0.0.1]:{port}", server_key.get_name(), server_key)

    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys", known_hosts)
    thread = Thread(target=serve, daemon=True)
    thread.start()
    yield RemoteProvider(Connection("SFTP", "127.0.0.1", port, "test", "secret")), root
    stop.set()
    listener.close()
    for transport in transports:
        transport.close()
    thread.join(timeout=3)


def test_sftp_real_upload_download_overwrite_rename_and_delete(sftp_server, tmp_path):
    remote, root = sftp_server
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "folder").mkdir()
    data = b"Real SFTP data\n" * 100_000
    (source / "folder" / "český.txt").write_bytes(data)
    local = LocalProvider()
    entries = local.list(str(source))
    copy_entries(local, str(source), remote, "/", entries, Event())
    assert (root / "folder" / "český.txt").read_bytes() == data
    assert preview(remote, "/folder/český.txt", limit=1234) == data[:1234]
    (source / "folder" / "český.txt").write_bytes(b"updated")
    copy_entries(local, str(source), remote, "/", entries, Event(), conflict="overwrite")
    remote.rename("/folder/český.txt", "/folder/new.txt")
    copy_entries(remote, "/", local, str(target), remote.list("/"), Event())
    assert (target / "folder" / "new.txt").read_bytes() == b"updated"
    remote.remove("/folder", remote.list("/")[0])
    assert not list(root.iterdir())


@pytest.mark.parametrize("transport", ["sftp_server", "tls_server"])
def test_encrypted_resume_and_cross_provider_move(transport, request, tmp_path, monkeypatch):
    from soovee_commander.resume import transfer
    from soovee_commander.advanced import move_entries
    from soovee_commander.operations import Cancelled
    values = request.getfixturevalue(transport)
    remote, root = values[:2]
    if transport == "tls_server":
        create_context = ssl.create_default_context
        monkeypatch.setattr("soovee_commander.providers.ssl.create_default_context", lambda: create_context(cafile=str(values[2])))
    local = LocalProvider()
    data = b"encrypted resume content" * 90_000
    (root / "download").write_bytes(data)
    downloads = tmp_path / "downloads"; downloads.mkdir()
    cancel = Event()
    def interrupt(message, count):
        if count:
            cancel.set()
    with pytest.raises(Cancelled):
        transfer(remote, "/download", local, str(downloads / "download"), cancel, interrupt)
    transfer(remote, "/download", local, str(downloads / "download"), Event())
    assert (downloads / "download").read_bytes() == data
    cancel = Event()
    with pytest.raises(Cancelled):
        transfer(local, str(downloads / "download"), remote, "/upload", cancel, interrupt)
    transfer(local, str(downloads / "download"), remote, "/upload", Event())
    assert (root / "upload").read_bytes() == data
    (root / "moved").mkdir()
    move_entries(local, str(downloads), remote, "/moved", local.list(str(downloads)), Event())
    assert not list(downloads.iterdir())
    assert (root / "moved" / "download").read_bytes() == data
