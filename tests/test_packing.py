from pathlib import Path
from threading import Event

import pytest
from test_core import ftp_server

from soovee_commander.operations import Cancelled, preview, copy_entries
from soovee_commander.packing import FORMATS, create_archive
from soovee_commander.providers import ArchiveProvider, LocalProvider


@pytest.mark.parametrize('format,extension', [(key, ext) for _, key, ext in FORMATS])
def test_create_browse_and_extract_each_integrated_format(tmp_path, format, extension):
    source, target = tmp_path / 'source', tmp_path / 'extracted'
    source.mkdir(); target.mkdir()
    (source / 'tree' / 'empty').mkdir(parents=True)
    (source / 'tree' / 'český.txt').write_bytes('Hello 🌍\n'.encode() * 10000)
    (source / 'zero').touch()
    path = tmp_path / ('packed' + extension)
    local = LocalProvider()
    create_archive(local, str(source), str(path), local.list(str(source)), Event(), format=format)
    provider = ArchiveProvider(str(path))
    assert preview(provider, '/tree/český.txt') == (source / 'tree' / 'český.txt').read_bytes()
    copy_entries(provider, '/', local, str(target), provider.list('/'), Event())
    assert (target / 'tree' / 'empty').is_dir()
    assert (target / 'tree' / 'český.txt').read_bytes() == (source / 'tree' / 'český.txt').read_bytes()
    assert (target / 'zero').read_bytes() == b''
    with pytest.raises(FileExistsError):
        create_archive(local, str(source), str(path), local.list(str(source)), Event(), format=format)


@pytest.mark.parametrize('format,extension', [('7z', '.7z'), ('tar.gz', '.tar.gz'), ('tar.xz', '.tar.xz')])
def test_packing_cancel_failure_does_not_publish_or_keep_temporary(tmp_path, format, extension):
    source, out = tmp_path / 'source', tmp_path / 'out'
    source.mkdir(); out.mkdir()
    (source / 'big').write_bytes(b'x' * 1000000)
    local, cancel = LocalProvider(), Event()
    def stop(message, count):
        if count:
            cancel.set()
    with pytest.raises(Cancelled):
        create_archive(local, str(source), str(out / ('result' + extension)), local.list(str(source)), cancel, stop, format)
    assert not list(out.iterdir())
    with pytest.raises(ValueError, match='inside'):
        create_archive(local, str(tmp_path), str(source / ('result' + extension)), [e for e in local.list(str(tmp_path)) if e.name == 'source'], Event(), format=format)


@pytest.mark.parametrize('format', ['7z', 'tar.gz'])
def test_archive_from_remote_provider_is_streamed_and_browsable(ftp_server, tmp_path, format):
    # Reuse the real FTP fixture for provider-neutral packing.
    remote, root = ftp_server
    (root / 'remote.txt').write_bytes(b'remote' * 10000)
    destination = tmp_path / ('remote.' + format)
    create_archive(remote, '/', str(destination), remote.list('/'), Event(), format=format)
    assert preview(ArchiveProvider(str(destination)), '/remote.txt') == b'remote' * 10000
