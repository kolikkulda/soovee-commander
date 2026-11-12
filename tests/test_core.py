import io
import os
from pathlib import Path
import stat
import tarfile
from threading import Event, Thread
import zipfile
import contextlib
import ftplib

import pytest

from soovee_commander.operations import Cancelled, copy_entries, create_zip, move_local, preview


@pytest.mark.parametrize('reject_publish', [False, True])
def test_ftp_server_without_replace_preserves_original_on_publish_failure(monkeypatch, reject_publish):
    from soovee_commander.providers import Connection, RemoteProvider
    files = {'/file.txt': b'original'}
    class Server:
        def storbinary(self, command, source, blocksize, callback):
            data = source.read(); files[command[5:]] = data; callback(data)
        def rename(self, source, target):
            if target in files or (reject_publish and source.endswith('.part') and target == '/file.txt'):
                raise ftplib.error_perm('550 File exists or rename refused')
            files[target] = files.pop(source)
        def delete(self, path): del files[path]
        def close(self): pass
    server = Server()
    provider = RemoteProvider(Connection('FTP', 'example.test', 21, 'test'))
    @contextlib.contextmanager
    def session(): yield server
    monkeypatch.setattr(provider, 'session', session)
    if reject_publish:
        with pytest.raises(ftplib.error_perm):
            provider.write_from('/file.txt', io.BytesIO(b'new'), lambda count: None, overwrite=True)
        assert files == {'/file.txt': b'original'}
    else:
        provider.write_from('/file.txt', io.BytesIO(b'new'), lambda count: None, overwrite=True)
        assert files == {'/file.txt': b'new'}


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='Requires POSIX special files')
def test_special_file_copy_and_packing_fail_without_publishing(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir()
    os.mkfifo(source / 'pipe')
    local = LocalProvider()
    entries = local.list(str(source))
    with pytest.raises(ValueError, match='regular files'):
        copy_entries(local, str(source), local, str(target), entries, Event())
    assert not list(target.iterdir())
    with pytest.raises(ValueError, match='regular files'):
        create_zip(local, str(source), str(target / 'result.zip'), entries, Event())
    assert not list(target.iterdir())
from soovee_commander.providers import ArchiveProvider, Connection, LocalProvider, RemoteProvider, safe_name


@pytest.fixture
def folders(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return source, target


@pytest.mark.parametrize("name", ["..", ".", "../bad", "/etc", "a\\b", "bad\0name", "bad\r\nDELE foo"])
def test_invalid_names(name):
    with pytest.raises(ValueError):
        safe_name(name)


def test_copy_tree_and_move(folders):
    source, target = folders
    (source / "tree").mkdir()
    (source / "tree" / "příliš.txt").write_text("žluťoučký", encoding="utf-8")
    provider = LocalProvider()
    entries = provider.list(str(source))
    move_local(provider, str(source), provider, str(target), entries, Event(), lambda *args: None)
    assert not (source / "tree").exists()
    assert (target / "tree" / "příliš.txt").read_text(encoding="utf-8") == "žluťoučký"


def test_conflict_never_overwrites(folders):
    source, target = folders
    (source / "a").write_text("new")
    (target / "a").write_text("original")
    provider = LocalProvider()
    with pytest.raises(FileExistsError):
        copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), Event())
    assert (target / "a").read_text() == "original"
    with pytest.raises(FileExistsError):
        provider.write_from(str(target / "a"), io.BytesIO(b"new"), lambda n: None)
    assert (target / "a").read_text() == "original"
    assert not list(target.glob(".stereo-*"))


def test_self_copy_and_cancellation(folders):
    source, target = folders
    (source / "tree").mkdir()
    (source / "tree" / "child").mkdir()
    provider = LocalProvider()
    with pytest.raises(ValueError):
        copy_entries(provider, str(source), provider, str(source / "tree" / "child"),
                     provider.list(str(source)), Event())
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), cancel)
    assert not list(target.iterdir())


def test_cancel_mid_file_removes_partial(folders):
    source, target = folders
    provider = LocalProvider()
    (source / "large").write_bytes(b"x" * 900_000)
    cancel = Event()

    def report(message, count):
        if message.startswith("Writing"):
            cancel.set()

    with pytest.raises(Cancelled):
        copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), cancel, report)
    assert not list(target.iterdir())
    assert (source / "large").exists()


@pytest.mark.parametrize("kind", ["zip", "tar.gz", "tar.bz2", "tar.xz"])
def test_archive_browse_preview_selected_extract(folders, kind):
    source, target = folders
    archive_path = source / f"data.{kind}"
    if kind == "zip":
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("nested/one.txt", "hello archive")
            archive.writestr("two.txt", "untouched")
            archive.writestr("../escape.txt", "bad")
            archive.writestr("/absolute.txt", "bad")
            archive.writestr("C:\\escape.txt", "bad")
    else:
        with tarfile.open(archive_path, {"tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[kind]) as archive:
            for name, content in [("nested/one.txt", b"hello archive"), ("two.txt", b"untouched"),
                                  ("../escape.txt", b"bad"), ("/absolute.txt", b"bad")]:
                item = tarfile.TarInfo(name)
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
    provider = ArchiveProvider(str(archive_path))
    assert {e.name for e in provider.list("/")} == {"nested", "two.txt"}
    assert preview(provider, "/nested/one.txt") == b"hello archive"
    assert list(target.iterdir()) == []
    copy_entries(provider, "/nested", LocalProvider(), str(target), provider.list("/nested"), Event())
    assert (target / "one.txt").read_text() == "hello archive"
    assert {p.name for p in target.iterdir()} == {"one.txt"}
    assert not (source.parent / "escape.txt").exists()


def test_archive_links_rejected(tmp_path):
    filename = tmp_path / "links.zip"
    with zipfile.ZipFile(filename, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    provider = ArchiveProvider(str(filename))
    with pytest.raises(ValueError):
        preview(provider, "/link")


def test_preview_is_bounded(tmp_path):
    filename = tmp_path / "large.zip"
    with zipfile.ZipFile(filename, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("huge.txt", b"x" * 3_000_000)
    assert len(preview(ArchiveProvider(str(filename)), "/huge.txt", limit=10_000)) == 10_000


@pytest.fixture
def ftp_server(tmp_path):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer

    root = tmp_path / "ftp"
    root.mkdir()
    authorizer = DummyAuthorizer()
    authorizer.add_user("test", "secret", str(root), perm="elradfmwMT")

    class Handler(FTPHandler):
        def on_login(self, username):
            logins.append(username)

    logins = []
    Handler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", 0), Handler)
    port = server.socket.getsockname()[1]
    stop = Event()

    def serve():
        while not stop.is_set():
            server.serve_forever(timeout=0.01, blocking=False, handle_exit=False)

    thread = Thread(target=serve, daemon=True)
    thread.start()
    provider = RemoteProvider(Connection("FTP", "127.0.0.1", port, "test", "secret"))
    provider._test_logins = logins
    yield provider, root
    stop.set()
    thread.join(timeout=2)
    server.close_all()


def test_real_ftp_upload_download_rename_delete(ftp_server, folders):
    remote, root = ftp_server
    source, target = folders
    (source / "nested").mkdir()
    (source / "nested" / "český.txt").write_text("obsah ✓", encoding="utf-8")
    local = LocalProvider()
    copy_entries(local, str(source), remote, "/", local.list(str(source)), Event())
    assert (root / "nested" / "český.txt").read_text(encoding="utf-8") == "obsah ✓"
    assert preview(remote, "/nested/český.txt") == "obsah ✓".encode()
    remote.rename("/nested/český.txt", "/nested/new.txt")
    copy_entries(remote, "/", local, str(target), remote.list("/"), Event())
    assert (target / "nested" / "new.txt").read_text(encoding="utf-8") == "obsah ✓"
    remote.remove("/nested", remote.list("/")[0])
    assert not list(root.iterdir())


def test_ftp_cancel_cleans_temporary(ftp_server):
    remote, root = ftp_server

    def abort(count):
        raise Cancelled()

    with pytest.raises(Cancelled):
        remote.write_from("/large.bin", io.BytesIO(b"x" * 900_000), abort)
    assert not list(root.iterdir())


def test_password_not_in_repr():
    assert "secret" not in repr(Connection("SFTP", "example.com", 22, "me", "secret"))


@pytest.mark.parametrize('failure', ['EOPNOTSUPP', 'EACCES'])
def test_local_exfat_fallback(tmp_path, monkeypatch, failure):
    import errno
    import os

    def unsupported(*args):
        raise OSError(getattr(errno, failure), "No hard links")

    monkeypatch.setattr(os, "link", unsupported)
    monkeypatch.setattr('soovee_commander.providers.rename_no_replace', lambda *args: False)
    provider = LocalProvider()
    destination = str(tmp_path / "output")
    provider.write_from(destination, io.BytesIO(b"contents"), lambda n: None)
    assert Path(destination).read_bytes() == b"contents"
    with pytest.raises(FileExistsError):
        provider.write_from(destination, io.BytesIO(b"replacement"), lambda n: None)
    assert Path(destination).read_bytes() == b"contents"
    assert not list(tmp_path.glob(".stereo-*"))


def test_sftp_uses_known_hosts_and_rejects_unknown(monkeypatch):
    import paramiko
    seen = {}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def load_system_host_keys(self):
            seen["known_hosts"] = True

        def set_missing_host_key_policy(self, policy):
            seen["policy"] = policy

        def connect(self, host, **kwargs):
            seen["connect"] = kwargs
            raise paramiko.SSHException("Unknown host")

    monkeypatch.setattr(paramiko, "SSHClient", Client)
    provider = RemoteProvider(Connection("SFTP", "example.com", 2222, "me", keyfile="key"))
    with pytest.raises(paramiko.SSHException):
        provider.list("/")
    assert seen["known_hosts"]
    assert isinstance(seen["policy"], paramiko.RejectPolicy)
    assert seen["connect"]["key_filename"] == "key"


@pytest.mark.parametrize("conflict", ["skip", "rename", "overwrite"])
def test_conflict_policies_preserve_expected_data(folders, conflict):
    source, target = folders
    (source / "a.txt").write_text("new")
    (target / "a.txt").write_text("original")
    provider = LocalProvider()
    copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), Event(), conflict=conflict)
    assert (target / "a.txt").read_text() == ("new" if conflict == "overwrite" else "original")
    if conflict == "rename":
        assert (target / "a (2).txt").read_text() == "new"


def test_merge_does_not_follow_destination_link(folders):
    source, target = folders
    (source / "tree").mkdir()
    outside = target / "outside"
    outside.mkdir()
    try:
        (target / "tree").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this system")
    provider = LocalProvider()
    with pytest.raises(FileExistsError):
        copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), Event(), conflict="overwrite")
    assert not list(outside.iterdir())


def test_direct_copy_without_spooling_preserves_metadata(folders, monkeypatch):
    import os
    import tempfile
    source, target = folders
    file = source / "executable"
    file.write_bytes(b"x" * 1_000_000)
    os.chmod(file, 0o751)
    os.utime(file, (1700000000, 1700000000))

    def forbidden(*args, **kwargs):
        pytest.fail("Local transfers must not stage a complete source file")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbidden)
    provider = LocalProvider()
    copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), Event())
    assert (target / file.name).read_bytes() == file.read_bytes()
    assert int((target / file.name).stat().st_mtime) == 1700000000
    if os.name != "nt":
        assert stat.S_IMODE((target / file.name).stat().st_mode) == 0o751


def test_zip_creation_roundtrip_empty_directory_and_cancel(folders):
    source, target = folders
    (source / "empty").mkdir()
    (source / "hello.txt").write_text("Ahoj ✓", encoding="utf-8")
    provider = LocalProvider()
    path = target / "created.zip"
    create_zip(provider, str(source), str(path), provider.list(str(source)), Event())
    archive = ArchiveProvider(str(path))
    assert {e.name for e in archive.list("/")} == {"empty", "hello.txt"}
    assert preview(archive, "/hello.txt").decode() == "Ahoj ✓"
    cancel = Event()

    def abort(message, count):
        cancel.set()

    with pytest.raises(Cancelled):
        create_zip(provider, str(source), str(target / "cancelled.zip"), provider.list(str(source)), cancel, abort)
    assert not (target / "cancelled.zip").exists()
    assert not list(target.glob(".stereo-*"))


def test_archive_reuses_index_during_multiple_extraction(folders, monkeypatch):
    source, target = folders
    path = source / "files.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for i in range(20):
            archive.writestr(f"dir/item-{i}.txt", str(i))
    provider = ArchiveProvider(str(path))
    original = provider._open
    opens = []

    def tracked():
        opens.append(1)
        return original()

    monkeypatch.setattr(provider, "_open", tracked)
    copy_entries(provider, "/dir", LocalProvider(), str(target), provider.list("/dir"), Event())
    assert len(opens) == 1
    assert len(list(target.iterdir())) == 20


def test_changed_archive_is_not_read_with_stale_index(tmp_path):
    path = tmp_path / "data.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a", "old")
    provider = ArchiveProvider(str(path))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("b", "new and bigger")
    with pytest.raises(RuntimeError, match="changed"):
        preview(provider, "/a")


def test_ftp_reuses_one_login_for_many_files(ftp_server, folders):
    remote, root = ftp_server
    source, target = folders
    provider = LocalProvider()
    for i in range(12):
        (source / f"item-{i}.txt").write_text(str(i))
    copy_entries(provider, str(source), remote, "/", provider.list(str(source)), Event())
    assert len(remote._test_logins) == 1
    copy_entries(remote, "/", provider, str(target), remote.list("/"), Event())
    assert len(remote._test_logins) == 3  # Standalone listing, then one download batch.
    assert len(list(target.iterdir())) == 12


def test_ftp_overwrite_and_conflict_rename(ftp_server, folders):
    remote, root = ftp_server
    source, _ = folders
    (source / "a.txt").write_text("new")
    (root / "a.txt").write_text("old")
    provider = LocalProvider()
    entries = provider.list(str(source))
    copy_entries(provider, str(source), remote, "/", entries, Event(), conflict="rename")
    assert (root / "a.txt").read_text() == "old"
    assert (root / "a (2).txt").read_text() == "new"
    copy_entries(provider, str(source), remote, "/", entries, Event(), conflict="overwrite")
    assert (root / "a.txt").read_text() == "new"


def test_same_volume_move_does_not_copy_contents(folders, monkeypatch):
    source, target = folders
    (source / "folder").mkdir()
    (source / "folder" / "file.txt").write_text("contents")
    provider = LocalProvider()

    def forbidden(*args, **kwargs):
        pytest.fail("Same-volume move must rename, not copy file contents")

    monkeypatch.setattr(provider, "read_to", forbidden)
    move_local(provider, str(source), provider, str(target), provider.list(str(source)), Event(), lambda *args: None)
    assert not (source / "folder").exists()
    assert (target / "folder" / "file.txt").read_text() == "contents"


def test_move_conflict_never_overwrites(folders):
    source, target = folders
    (source / "a").write_text("source")
    (target / "a").write_text("target")
    provider = LocalProvider()
    with pytest.raises(FileExistsError):
        move_local(provider, str(source), provider, str(target), provider.list(str(source)), Event(), lambda *args: None)
    assert (source / "a").read_text() == "source"
    assert (target / "a").read_text() == "target"


def test_cross_volume_move_preserves_changed_source_tree(folders, monkeypatch):
    source, target = folders
    (source / "folder").mkdir()
    (source / "folder" / "a").write_bytes(b"x" * 1_000_000)
    monkeypatch.setattr("soovee_commander.operations.rename_no_replace", lambda *args: False)
    provider = LocalProvider()

    def change_source(message, count):
        (source / "folder" / "new-file").write_text("created during transfer")

    with pytest.raises(IOError, match="changed"):
        move_local(provider, str(source), provider, str(target), provider.list(str(source)), Event(), change_source)
    assert (source / "folder" / "new-file").exists()
    assert (source / "folder" / "a").exists()
    assert (target / "folder" / "a").read_bytes() == b"x" * 1_000_000


def test_changing_file_does_not_publish_incomplete_copy(folders):
    source, target = folders
    path = source / "a"
    path.write_bytes(b"x" * 1_000_000)
    provider = LocalProvider()
    changed = False

    def change_source(message, count):
        nonlocal changed
        if not changed:
            with path.open("ab") as file:
                file.write(b"new content")
            changed = True

    with pytest.raises(IOError, match="changed"):
        copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), Event(), change_source)
    assert not list(target.iterdir())


def test_traditional_encrypted_zip_password():
    path = Path(__file__).parent / "data" / "encrypted.zip"
    provider = ArchiveProvider(str(path), password=b"test-pass")
    assert provider.encrypted
    assert preview(provider, "/secret.txt").decode() == "Test encrypted ZIP ✓\n"
    with pytest.raises(RuntimeError):
        preview(ArchiveProvider(str(path), password=b"wrong"), "/secret.txt")


def test_changed_local_upload_does_not_publish_remote_file(ftp_server, folders):
    remote, root = ftp_server
    source, _ = folders
    path = source / "changing.bin"
    path.write_bytes(b"x" * 1_000_000)
    provider = LocalProvider()
    changed = False

    def mutate(message, count):
        nonlocal changed
        if not changed:
            with path.open("ab") as stream:
                stream.write(b"changed")
            changed = True

    with pytest.raises(IOError, match="changed"):
        copy_entries(provider, str(source), remote, "/", provider.list(str(source)), Event(), mutate)
    assert not list(root.iterdir())


def test_ftp_search_after_early_content_match_reconnects(ftp_server):
    from soovee_commander.advanced import search
    remote, root = ftp_server
    (root / "a.txt").write_bytes(b"needle" + b"x" * 900_000)
    (root / "b.txt").write_text("needle too")
    result, errors = search(remote, "/", "*.txt", "needle", Event())
    assert {r[0] for r in result} == {"a.txt", "b.txt"}
    assert not errors


def test_ftp_resume_download_and_upload(ftp_server, tmp_path):
    from soovee_commander.resume import transfer
    remote, root = ftp_server
    local = LocalProvider()
    downloads = tmp_path / "downloads"; downloads.mkdir()
    data = bytes(range(256)) * 8000
    (root / "download.bin").write_bytes(data)
    cancel = Event()
    def interrupt(message, count):
        if count:
            cancel.set()
    with pytest.raises(Cancelled):
        transfer(remote, "/download.bin", local, str(downloads / "download.bin"), cancel, interrupt)
    partials = list(downloads.glob(".stereo-resume-*.part"))
    assert len(partials) == 1 and 0 < partials[0].stat().st_size < len(data)
    assert not (downloads / "download.bin").exists()
    messages = []
    transfer(remote, "/download.bin", local, str(downloads / "download.bin"), Event(), lambda m, c: messages.append(m))
    assert (downloads / "download.bin").read_bytes() == data
    assert not list(downloads.glob(".stereo-resume-*"))
    assert any("Resuming from" in m and "from 0 B" not in m for m in messages)
    (tmp_path / "upload.bin").write_bytes(data)
    cancel = Event()
    with pytest.raises(Cancelled):
        transfer(local, str(tmp_path / "upload.bin"), remote, "/uploaded.bin", cancel, interrupt)
    partials = list(root.glob(".stereo-resume-*.part"))
    assert len(partials) == 1
    assert not (root / "uploaded.bin").exists()
    transfer(local, str(tmp_path / "upload.bin"), remote, "/uploaded.bin", Event())
    assert (root / "uploaded.bin").read_bytes() == data
    assert not list(root.glob(".stereo-resume-*"))


def test_ftp_move_and_multi_rename(ftp_server, tmp_path):
    from soovee_commander.advanced import move_entries, multi_rename
    remote, root = ftp_server
    local = LocalProvider()
    (root / "from").mkdir(); (root / "to").mkdir()
    (root / "from" / "one").write_text("content")
    entries = remote.list("/from")
    move_entries(remote, "/from", remote, "/to", entries, Event())
    assert not (root / "from" / "one").exists()
    entries = remote.list("/to")
    multi_rename(remote, "/to", entries, ["two"], Event())
    assert (root / "to" / "two").read_text() == "content"
    target = tmp_path / "target"; target.mkdir()
    move_entries(remote, "/to", local, str(target), remote.list("/to"), Event())
    assert (target / "two").read_text() == "content"
    assert not (root / "to" / "two").exists()


def test_legacy_ftp_list_formats_preserve_names_and_reject_unknown():
    from soovee_commander.ftp_listing import parse_listing
    unix = parse_listing(['total 4', 'drwxr-xr-x 2 user group 4096 Oct 30 12:10 Folder name',
                          '-rw-r--r-- 1 user group 42 Jan 12 2025 hello world.txt',
                          'lrwxr-xr-x 1 user group 6 Oct 30 12:11 alias -> target'])
    assert [(e.name, e.is_dir, e.size, e.is_link) for e in unix] == [('Folder name', True, 4096, False), ('hello world.txt', False, 42, False), ('alias', False, 6, True)]
    dos = parse_listing(['10-30-26  12:00AM       <DIR>          Photos', '10-30-2026  01:30PM                 512 a b.txt'])
    assert dos[0].is_dir and dos[1].size == 512 and dos[1].name == 'a b.txt'
    with pytest.raises(ValueError, match='Cannot interpret'):
        parse_listing(['unknown format that must not silently lose files'])


def test_real_legacy_ftp_upload_browse_download_and_rename(ftp_server, folders, monkeypatch):
    from pyftpdlib.handlers import FTPHandler
    monkeypatch.setattr(FTPHandler, 'ftp_MLSD', lambda self, path: self.respond('502 MLSD not implemented'))
    remote, root = ftp_server
    source, target = folders
    (source / 'folder with spaces').mkdir()
    (source / 'folder with spaces' / 'hello.txt').write_bytes(b'legacy FTP works')
    local = LocalProvider()
    copy_entries(local, str(source), remote, '/', local.list(str(source)), Event())
    assert remote.list('/')[0].name == 'folder with spaces'
    copy_entries(remote, '/', local, str(target), remote.list('/'), Event())
    assert (target / 'folder with spaces' / 'hello.txt').read_bytes() == b'legacy FTP works'
    remote.rename('/folder with spaces/hello.txt', '/folder with spaces/renamed.txt')
    assert remote.list('/folder with spaces')[0].name == 'renamed.txt'


def test_transfer_events_have_recursive_total_paths_and_monotonic_file_bytes(folders):
    import json
    from soovee_commander.transfer_status import PREFIX
    source, target = folders
    (source / 'nested').mkdir()
    (source / 'nested' / 'large').write_bytes(b'x' * 700000)
    (source / 'small').write_bytes(b'abc')
    events = []
    provider = LocalProvider()
    copy_entries(provider, str(source), provider, str(target), provider.list(str(source)), Event(),
                 lambda message, count: events.append(json.loads(message[len(PREFIX):])) if message.startswith(PREFIX) else None)
    plan = next(e for e in events if e['event'] == 'plan')
    assert plan['bytes'] == 700003 and plan['files'] == 2
    assert sum(e['size'] for e in events if e['event'] == 'file_done') == 700003
    current = 0
    for event in events:
        if event['event'] == 'file':
            current = 0
            assert event['source'].startswith(str(source)) and event['destination'].startswith(str(target))
        elif event['event'] == 'advance':
            assert event['bytes'] >= current
            current = event['bytes']


def test_copy_metadata_falls_back_when_attributes_are_refused(tmp_path, monkeypatch):
    """Android SELinux refuses extended attributes with EACCES; copies must still succeed."""
    import os, shutil
    from soovee_commander import providers
    source = tmp_path / 'a.txt'; source.write_text('a'); os.utime(source, (1_000_000, 1_000_000))
    target = tmp_path / 'b.txt'; target.write_text('a')
    def refuse(*args, **kwargs): raise PermissionError(13, 'Permission denied')
    monkeypatch.setattr(shutil, 'copystat', refuse)
    providers.copy_metadata(str(source), str(target))
    assert int(target.stat().st_mtime) == 1_000_000


def test_cross_volume_move_removes_read_only_source(folders, monkeypatch):
    # Windows refuses to delete read-only items (WinError 5); F6 then left the source behind.
    import stat
    source, target = folders
    (source / "folder").mkdir()
    (source / "folder" / "a.txt").write_text("contents")
    (source / "single.txt").write_text("one")
    for item in (source / "folder" / "a.txt", source / "single.txt"):
        os.chmod(item, stat.S_IREAD)
    monkeypatch.setattr("soovee_commander.operations.rename_no_replace", lambda *args: False)
    provider = LocalProvider()
    move_local(provider, str(source), provider, str(target), provider.list(str(source)), Event(), lambda *args: None)
    assert not any(source.iterdir())
    assert (target / "folder" / "a.txt").read_text() == "contents"
    assert (target / "single.txt").read_text() == "one"
    for item in (target / "folder" / "a.txt", target / "single.txt"):
        os.chmod(item, stat.S_IWRITE | stat.S_IREAD)


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions")
def test_windows_junction_is_listed_as_link_and_not_scanned(tmp_path):
    import _winapi
    from soovee_commander.advanced import folder_size
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 1000)
    root = tmp_path / "root"
    root.mkdir()
    _winapi.CreateJunction(str(outside), str(root / "junction"))
    provider = LocalProvider()
    [entry] = provider.list(str(root))
    assert entry.is_link and entry.is_dir
    assert folder_size(provider, str(root), Event()) == (0, 0, 0)
    provider.remove(str(root / "junction"), entry)
    assert (outside / "big.bin").exists() and not (root / "junction").exists()


def _windows_drive_folder(drive):
    import tempfile
    try:
        return Path(tempfile.mkdtemp(prefix="soovee-move-", dir=drive + "\\"))
    except OSError:
        return None


@pytest.mark.skipif(os.name != "nt", reason="Windows system folders")
def test_windows_folder_size_of_real_profile_with_denied_junctions():
    # C:\Users\Default holds junctions such as "Application Data" whose ACL denies
    # listing; scanning into them made every folder on C:\ fail with WinError 5.
    from soovee_commander.advanced import folder_size
    provider = LocalProvider()
    root = os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "Users", "Default")
    links = {e.name for e in provider.list(root) if e.is_link}
    assert "Application Data" in links or not os.path.lexists(os.path.join(root, "Application Data"))
    size, files, folders = folder_size(provider, root, Event())
    assert files > 0 and size > 0


@pytest.mark.skipif(os.name != "nt", reason="Windows drives")
def test_windows_move_folder_between_drives():
    # F6 from C: to D: copies and then deletes the source; read-only items must not stop it.
    import shutil
    drives = [d for d in ("C:", "D:") if os.path.exists(d + "\\")]
    if len(drives) < 2:
        pytest.skip("needs two drives")
    source, target = _windows_drive_folder("C:"), _windows_drive_folder("D:")
    if source is None or target is None:
        pytest.skip("drive not writable")
    try:
        folder = source / "My folder"
        (folder / "inner").mkdir(parents=True)
        (folder / "inner" / "file.txt").write_text("data")
        (folder / "locked.txt").write_text("read only")
        os.chmod(folder / "locked.txt", stat.S_IREAD)
        os.chmod(folder / "inner", stat.S_IREAD)   # read-only folder attribute, as on customized folders
        provider = LocalProvider()
        move_local(provider, str(source), provider, str(target), provider.list(str(source)), Event(), lambda *args: None)
        assert not folder.exists()
        assert (target / "My folder" / "inner" / "file.txt").read_text() == "data"
    finally:
        for base in (source, target):
            for directory, folders, names in os.walk(base):
                for name in folders + names:
                    with contextlib.suppress(OSError):
                        os.chmod(os.path.join(directory, name), stat.S_IWRITE | stat.S_IREAD)
            shutil.rmtree(base, ignore_errors=True)
