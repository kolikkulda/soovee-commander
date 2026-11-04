"""Shared native bridge: durable identity and ports, scoped files, safe imports."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def mobile():
    source = Path(__file__).parents[1] / 'mobile/shared/python/soovee_mobile.py'
    spec = importlib.util.spec_from_file_location('soovee_mobile_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    module.stop()


class Callbacks:
    def approve(self, *args):
        raise AssertionError('No unrequested pairing approval')

    def activity(self, payload):
        pass


def test_native_restart_keeps_name_port_role_and_shared_scope(mobile, tmp_path):
    from soovee_commander.lan_protocol import require_tls_psk
    try:
        require_tls_psk()
    except RuntimeError as error:
        pytest.skip(str(error))
    state, shared = tmp_path / 'state', tmp_path / 'Shared'
    first = json.loads(mobile.start(state, shared, 'Test TV', 'tv', Callbacks()))
    assert first['role'] == 'controlled'
    assert len(first['code']) == 8 and first['qr']
    mobile.set_name('Living room TV')
    mobile.stop()
    second = json.loads(mobile.start(state, shared, 'Factory name', 'tv', Callbacks()))
    assert second['port'] == first['port']
    assert second['name'] == 'Living room TV'
    assert second['role'] == 'controlled'
    previous = mobile.callbacks
    replacement = Callbacks()
    mobile.start(state, shared, 'Ignored', 'tv', replacement)
    mobile.stop(previous)
    assert mobile.service is not None and mobile.service.port == first['port']
    mobile.stop(replacement)
    assert mobile.service is None
    with pytest.raises(ValueError, match='outside'):
        mobile.browse('', '/../state')


def test_native_import_does_not_overwrite_and_removes_partial_files(mobile, tmp_path):
    mobile.shared = tmp_path / 'Shared'
    mobile.shared.mkdir()
    source = tmp_path / 'source.bin'
    source.write_bytes(b'safe native import' * 1000)
    with source.open('rb') as stream:
        result = Path(mobile.import_file('import.bin', stream.fileno()))
    assert result.read_bytes() == source.read_bytes()
    with source.open('rb') as stream, pytest.raises(FileExistsError):
        mobile.import_file('import.bin', stream.fileno())
    assert list(mobile.shared.iterdir()) == [result]
    with source.open('rb') as stream, pytest.raises(ValueError):
        mobile.import_file('../escape.bin', stream.fileno())


def test_storage_consent_capacity_private_paths_and_revocation(mobile,tmp_path):
    from soovee_commander.lan import TransferService
    from soovee_commander.device_files import DeviceProvider
    from soovee_commander.lan_protocol import TransferError
    class Allow(Callbacks):
        def approve(self,*args): return True
    shared=tmp_path/'Shared';storage=tmp_path/'public';storage.mkdir()
    (storage/'Download').mkdir();(storage/'Android/data').mkdir(parents=True);(storage/'Android/media').mkdir()
    mobile.start(tmp_path/'tv-state',shared,'Test TV','tv',Allow())
    (shared/'keep.mp4').write_bytes(b'original TV upload')
    roots=json.dumps([dict(key='app',name='Shared',path=str(shared),writable=True),dict(key='internal',name='Internal storage',path=str(storage),writable=True)])
    mobile.configure_storage(roots,False)
    controller=TransferService(tmp_path/'controller','Test Mac');controller.start()
    try:
        peer=controller.pair('127.0.0.1',mobile.service.port,mobile.service.pairing['code'],approve=lambda peer:True)
        remote=DeviceProvider(controller,peer.id)
        assert [entry.name for entry in remote.list('/')]==['Shared']
        mobile.configure_storage(roots,True)
        assert {entry.name for entry in remote.list('/')}=={'Shared','Internal storage'}
        capacity=remote.space('/Internal storage/Download')
        assert capacity['total']>0 and 0<=capacity['available']<=capacity['free']<=capacity['total']
        assert capacity['path']==str(storage/'Download')
        assert [entry.name for entry in remote.list('/Internal storage/Android')]==['media']
        with pytest.raises(TransferError): remote.list('/Internal storage/Android/data')
        with pytest.raises(ValueError): mobile.local_file('/Internal storage/Android/data')
        with pytest.raises(ValueError): mobile.local_file('/Shared/../tv-state/devices.json')
        mobile.configure_storage(roots,False)
        assert [entry.name for entry in remote.list('/')]==['Shared']
        assert (shared/'keep.mp4').read_bytes()==b'original TV upload'
        with pytest.raises(TransferError): remote.list('/Internal storage/Download')
    finally: controller.stop()


def test_native_local_actions_copy_move_names_and_root_protection(mobile,tmp_path):
    shared=tmp_path/'Shared';mobile.start(tmp_path/'state',shared,'Test TV','tv',Callbacks())
    mobile.configure_storage(json.dumps([dict(key='app',name='Shared',path=str(shared),writable=True)]),False)
    (shared/'notes.txt').write_text('keep original')
    mobile.mutate_item('','/Shared','mkdir','Documents')
    mobile.copy_local_item('/Shared/notes.txt','/Shared/Documents',False)
    assert (shared/'Documents/notes.txt').read_text()==(shared/'notes.txt').read_text()
    mobile.mutate_item('','/Shared/Documents/notes.txt','rename','renamed.txt')
    assert not (shared/'Documents/notes.txt').exists()
    mobile.copy_local_item('/Shared/notes.txt','/Shared/Documents',True)
    assert not (shared/'notes.txt').exists() and (shared/'Documents/notes.txt').read_text()=='keep original'
    with pytest.raises(ValueError):mobile.mutate_item('','/Shared','remove')
    with pytest.raises(ValueError):mobile.mutate_item('','/Shared','rename','escape')
    with pytest.raises(ValueError):mobile.mutate_item('','/Shared/Documents','rename','../escape')
    mobile.mutate_item('','/Shared/Documents','remove')
    assert list(shared.iterdir())==[]


def test_batch_transfer_collision_and_default_app_storage(mobile, tmp_path):
    shared=tmp_path/'Shared'
    mobile.start(tmp_path/'state',shared,'Test phone','phone',Callbacks())
    assert json.loads(mobile.browse_local_path('/'))[0]['name']=='Shared'
    (shared/'destination').mkdir()
    (shared/'first.txt').write_text('first')
    (shared/'second.txt').write_text('second')
    paths=json.dumps(['/Shared/first.txt','/Shared/second.txt'])
    mobile.transfer_items('',paths,'','/Shared/destination')
    assert (shared/'destination/first.txt').read_text()=='first'
    assert (shared/'destination/second.txt').read_text()=='second'
    status=json.loads(mobile.operation_snapshot())
    assert status['status']=='done' and status['completed']==2 and status['bytes']==11
    (shared/'first.txt').write_text('changed')
    mobile.transfer_items('',paths,'','/Shared/destination')  # Existing targets stay; copies get free names.
    assert (shared/'destination/first.txt').read_text()=='first'
    assert (shared/'destination/first (2).txt').read_text()=='changed'
    assert (shared/'destination/second (2).txt').read_text()=='second'
    assert json.loads(mobile.operation_snapshot())['status']=='done'
    with pytest.raises(ValueError):mobile.transfer_items('',json.dumps(['/Shared']),'','/Shared/destination')
    with pytest.raises(ValueError):mobile.transfer_items('',paths,'peer','/Shared',True)


def test_batch_cancel_keeps_source_and_discards_partial_copy(mobile, tmp_path):
    shared=tmp_path/'Shared'
    class StopOnProgress(Callbacks):
        def activity(self,payload):
            if json.loads(payload).get('bytes',0)>0:mobile.cancel_operation()
    mobile.start(tmp_path/'state',shared,'Test phone','phone',StopOnProgress())
    (shared/'destination').mkdir()
    source=shared/'large.bin';source.write_bytes(b'a'*(4*1024*1024))
    from soovee_commander.operations import Cancelled
    with pytest.raises(Cancelled):mobile.transfer_items('',json.dumps(['/Shared/large.bin']),'','/Shared/destination')
    assert source.stat().st_size==4*1024*1024
    assert not (shared/'destination/large.bin').exists()
    assert json.loads(mobile.operation_snapshot())['status']=='canceled'


def test_batch_device_roundtrip_and_remote_root_guard(mobile,tmp_path):
    from soovee_commander.lan import TransferService
    shared=tmp_path/'Shared';mobile.start(tmp_path/'state',shared,'Phone','phone',Callbacks())
    remote_folder=tmp_path/'TV files';remote_folder.mkdir()
    tv=TransferService(tmp_path/'tv-state','TV',approve_pair=lambda peer:True,device_kind='tv')
    tv.start()
    try:
        peer=mobile.service.pair('127.0.0.1',tv.port,tv.begin_pairing(),approve=lambda peer:True)
        tv.shares.add(remote_folder,'Shared',mobile.service.store.id,writable=True)
        (shared/'video.mp4').write_bytes(bytes(range(256))*10000)
        mobile.transfer_items('',json.dumps(['/Shared/video.mp4']),peer.id,'/Shared')
        assert (remote_folder/'video.mp4').read_bytes()==(shared/'video.mp4').read_bytes()
        (shared/'downloads').mkdir()
        mobile.transfer_items(peer.id,json.dumps(['/Shared/video.mp4']),'','/Shared/downloads')
        assert (shared/'downloads/video.mp4').read_bytes()==(remote_folder/'video.mp4').read_bytes()
        mobile.mutate_item(peer.id,'/Shared/video.mp4','rename','renamed.mp4')
        assert (remote_folder/'renamed.mp4').exists()
        mobile.mutate_item(peer.id,'/Shared/renamed.mp4','remove')
        assert not list(remote_folder.iterdir())
        with pytest.raises(ValueError):mobile.transfer_items(peer.id,json.dumps(['/Shared']),'','/Shared/downloads')
        (remote_folder/'Movies').mkdir()
        with pytest.raises(ValueError):mobile.transfer_items(peer.id,json.dumps(['/Shared/Movies']),peer.id,'/Shared/Movies')
    finally:tv.stop()


def test_new_file_search_compress_and_extract(mobile, tmp_path):
    shared=tmp_path/'Shared'
    mobile.start(tmp_path/'state',shared,'Test phone','phone',Callbacks())
    (shared/'docs/deep').mkdir(parents=True)
    (shared/'docs/deep/Report.txt').write_text('report')
    (shared/'docs/notes.md').write_text('notes')
    mobile.mutate_item('','/Shared/docs','newfile','empty.txt')
    assert (shared/'docs/empty.txt').read_text()==''
    with pytest.raises(FileExistsError):mobile.mutate_item('','/Shared/docs','newfile','empty.txt')  # never replaced
    found=json.loads(mobile.search_local('/Shared','REPORT'))
    assert found['complete'] and [r['name'] for r in found['results']]==['docs/deep/Report.txt']
    packed=json.loads(mobile.compress_items(json.dumps(['/Shared/docs/deep','/Shared/docs/notes.md']),'Bundle'))
    assert packed['file']=='Bundle.zip' and (shared/'docs/Bundle.zip').exists()
    unpacked=json.loads(mobile.extract_archive('/Shared/docs/Bundle.zip'))
    assert unpacked['folder']=='Bundle'
    assert (shared/'docs/Bundle/deep/Report.txt').read_text()=='report'
    assert (shared/'docs/Bundle/notes.md').read_text()=='notes'
    assert json.loads(mobile.extract_archive('/Shared/docs/Bundle.zip'))['folder']=='Bundle (2)'  # existing folder kept
    assert json.loads(mobile.operation_snapshot())['status']=='done'


def test_copy_progress_reports_totals(mobile, tmp_path):
    shared=tmp_path/'Shared'
    mobile.start(tmp_path/'state',shared,'Test phone','phone',Callbacks())
    (shared/'in/sub').mkdir(parents=True); (shared/'out').mkdir()
    (shared/'in/a.bin').write_bytes(b'x'*1000); (shared/'in/sub/b.bin').write_bytes(b'y'*500)
    mobile.transfer_items('',json.dumps(['/Shared/in']),'','/Shared/out')
    state=json.loads(mobile.operation_snapshot())
    assert state['total']==1500 and state['total_files']==2 and state['bytes']==1500


def test_duplicate_file_and_folder_get_free_names(mobile, tmp_path):
    shared=tmp_path/'Shared'
    mobile.start(tmp_path/'state',shared,'Test phone','phone',Callbacks())
    (shared/'Report.txt').write_text('r'); (shared/'Album/inner').mkdir(parents=True); (shared/'Album/inner/a.jpg').write_bytes(b'a'*10)
    assert json.loads(mobile.duplicate_item('/Shared/Report.txt'))['file']=='Report (2).txt'
    assert json.loads(mobile.duplicate_item('/Shared/Report.txt'))['file']=='Report (3).txt'
    assert json.loads(mobile.duplicate_item('/Shared/Album'))['file']=='Album (2)'
    assert (shared/'Album (2)/inner/a.jpg').read_bytes()==b'a'*10
    state=json.loads(mobile.operation_snapshot()); assert state['status']=='done' and state['total']==10
