"""Real loopback integration of pairing, authorization, resumable transfers and publication."""
from pathlib import Path
from threading import Event
import time

import pytest


def test_cancelable_message_preserves_partial_frames_across_poll_timeouts():
    import socket
    import struct
    import time
    from threading import Thread
    from soovee_commander.lan_protocol import canonical, receive_message
    left, right = socket.socketpair()
    right.settimeout(3)
    message = dict(value='partial frame')
    raw = canonical(message)
    frame = struct.pack('!I', len(raw)) + raw
    def send():
        left.sendall(frame[:2]); time.sleep(.3)
        left.sendall(frame[2:10]); time.sleep(.3)
        left.sendall(frame[10:])
    worker = Thread(target=send)
    try:
        worker.start()
        assert receive_message(right, Event()) == message
        assert right.gettimeout() == 3
    finally:
        worker.join(2); left.close(); right.close()

from soovee_commander.lan import TransferService
from soovee_commander.lan_files import plan_sources, ReceiveBundle, validate_manifest
from soovee_commander.lan_protocol import TransferError, invitation, parse_invitation
from soovee_commander.operations import Cancelled


@pytest.fixture
def devices(tmp_path):
    received_a, received_b = tmp_path / 'received-a', tmp_path / 'received-b'
    received_a.mkdir(); received_b.mkdir()
    events = []
    a = TransferService(tmp_path / 'a', 'Computer A', approve_pair=lambda peer: True,
                        approve_offer=lambda *args: received_a, event=events.append)
    b = TransferService(tmp_path / 'b', 'Computer B', approve_pair=lambda peer: True,
                        approve_offer=lambda *args: received_b, event=events.append)
    a.start(); b.start()
    yield a, b, received_a, received_b, events
    a.stop(); b.stop()


def pair(a, b):
    code = b.begin_pairing()
    host, port, parsed_code = parse_invitation(b.pairing_link('127.0.0.1'))
    assert code == parsed_code
    peer = a.pair(host, port, parsed_code, approve=lambda peer: True)
    assert peer.id == b.store.id
    assert b.store.get(a.store.id).secret == peer.secret
    return peer


@pytest.mark.skipif(__import__('os').name == 'nt', reason='Native mobile runtime uses POSIX file locks')
def test_native_runtime_receives_without_qt_and_serializes_profile(devices, tmp_path, monkeypatch):
    from soovee_commander.lan_store import HeadlessProfileLock
    import sys
    first = HeadlessProfileLock(tmp_path / 'receive.lock')
    second = HeadlessProfileLock(tmp_path / 'receive.lock')
    assert first.tryLock(0)
    try:
        assert not second.tryLock(0)
    finally:
        first.unlock()
    assert second.tryLock(0)
    second.unlock()
    a, b, _, received, _ = devices
    peer = pair(a, b)
    monkeypatch.setitem(sys.modules, 'PySide6.QtCore', None)
    source = tmp_path / 'native.txt'
    source.write_bytes(b'native receiver without Qt')
    output = Path(a.send(peer.id, [source]))
    assert output.parent == received
    assert (output / source.name).read_bytes() == source.read_bytes()


def test_real_pairing_transfer_both_directions_empty_folders_and_no_overwrite(devices, tmp_path):
    a, b, ra, rb, events = devices
    peer = pair(a, b)
    tree = tmp_path / 'Project'
    tree.mkdir(); (tree / 'empty').mkdir(); (tree / 'nested').mkdir()
    (tree / 'nested' / 'data.txt').write_bytes(b'hello' * 90000)
    output = Path(a.send(peer.id, [tree]))
    assert output.parent == rb
    assert (output / 'Project/empty').is_dir()
    assert (output / 'Project/nested/data.txt').read_bytes() == b'hello' * 90000
    assert Path(a.send(peer.id, [tree])) == output
    (output / 'Project/nested/data.txt').write_text('keep existing data')
    with pytest.raises(TransferError):
        a.send(peer.id, [tree])
    assert (output / 'Project/nested/data.txt').read_text() == 'keep existing data'
    source = tmp_path / 'back.txt'; source.write_bytes(b'backwards')
    back = Path(b.send(a.store.id, [source]))
    assert back.parent == ra and (back / 'back.txt').read_bytes() == b'backwards'
    assert any(e['kind'] == 'completed' for e in events)
    assert 'secret=' not in repr(peer)


def test_wrong_expired_canceled_and_consumed_pairing_codes(devices):
    a, b, _, _, _ = devices
    code = b.begin_pairing()
    wrong = ('0' if code[0] != '0' else '1') + code[1:]
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, wrong, approve=lambda peer: True)
    assert not a.store.peers() and not b.store.peers()
    b.begin_pairing(lifetime=-1)
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, code, approve=lambda peer: True)
    b.begin_pairing(); b.cancel_pairing()
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, code, approve=lambda peer: True)
    pair(a, b)
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, code, approve=lambda peer: True)


def test_pairing_requires_both_approvals_and_receive_requires_approval(devices, tmp_path):
    a, b, _, rb, _ = devices
    code = b.begin_pairing()
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, code, approve=lambda peer: False)
    assert not a.store.peers() and not b.store.peers()
    b.approve_pair = lambda peer: False
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, code, approve=lambda peer: True)
    assert not a.store.peers() and not b.store.peers()
    b.approve_pair = lambda peer: True
    peer = pair(a, b)
    b.approve_offer = lambda *args: None
    source = tmp_path / 'private.txt'; source.write_bytes(b'private')
    with pytest.raises(TransferError, match='declined'):
        a.send(peer.id, [source])
    assert not list(rb.iterdir())


def test_interruption_resume_and_source_changes(devices, tmp_path):
    a, b, _, rb, _ = devices
    peer = pair(a, b)
    source = tmp_path / 'large.bin'; source.write_bytes(bytes(range(256)) * 16000)
    plan = plan_sources([source])
    cancel = Event()
    from soovee_commander.transfer_status import PREFIX
    def interrupt(message, count):
        if message.startswith(PREFIX) and '"advance"' in message:
            cancel.set()
    with pytest.raises(Cancelled):
        a.send(peer.id, [], cancel, interrupt, plan=plan)
    deadline = time.monotonic() + 3
    while b.offers and time.monotonic() < deadline:
        time.sleep(.01)
    assert not list(rb.glob('Soovee-*'))
    messages = []
    output = Path(a.send(peer.id, [], report=lambda message, count: messages.append(message), plan=plan))
    assert (output / source.name).read_bytes() == source.read_bytes()
    assert any('"resume"' in message for message in messages)
    old = plan_sources([source]); source.write_bytes(b'changed')
    with pytest.raises(TransferError, match='changed'):
        a.send(peer.id, [], plan=old)


def test_removed_pair_and_persistent_pair_store(devices, tmp_path):
    a, b, _, _, _ = devices
    peer = pair(a, b)
    from soovee_commander.lan_store import DeviceStore
    reloaded = DeviceStore(a.store.directory)
    assert reloaded.get(peer.id).secret == peer.secret
    b.remove_peer(a.store.id)
    source = tmp_path / 'file'; source.write_text('data')
    with pytest.raises((TransferError, OSError)):
        a.send(peer.id, [source])


@pytest.mark.parametrize('path', ['../outside', '/absolute', 'C:/outside', 'safe/../../outside', 'back\\slash', 'CON.txt', 'trailing.', 'bad\nname'])
def test_malicious_manifest_paths_are_rejected(path):
    import hashlib
    with pytest.raises(TransferError):
        validate_manifest(dict(version=1, items=[dict(path=path, kind='file', size=0, sha256=hashlib.sha256(b'').hexdigest(), mtime_ns=0)]))


def test_checksum_failure_never_publishes(devices, tmp_path):
    import socket
    a, b, _, rb, _ = devices
    source = tmp_path / 'file.txt'; source.write_bytes(b'expected')
    plan = plan_sources([source])
    bundle = ReceiveBundle(rb, a.store.id, plan.manifest, Event())
    left, right = socket.socketpair()
    try:
        left.sendall(b'malicious')
        with pytest.raises(TransferError, match='integrity'):
            bundle.receive_file(0, 0, right, lambda value: None)
        assert not bundle.output.exists() and not bundle.partial(0).exists()
    finally:
        left.close(); right.close()


def test_pairing_rate_limit_and_rotation_before_approval(devices):
    a, b, _, _, _ = devices
    code = b.begin_pairing()
    wrong = ('0' if code[0] != '0' else '1') + code[1:]
    for _ in range(5):
        with pytest.raises(TransferError):
            a.pair('127.0.0.1', b.port, wrong, approve=lambda peer: True)
        deadline = time.monotonic() + 2
        while b.pair_lock.locked() and time.monotonic() < deadline:
            time.sleep(.005)
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, code, approve=lambda peer: True)
    code = b.begin_pairing()
    def rotate(peer):
        b.begin_pairing()
        return True
    b.approve_pair = rotate
    with pytest.raises(TransferError):
        a.pair('127.0.0.1', b.port, code, approve=lambda peer: True)
    assert not a.store.peers() and not b.store.peers()


def test_cancel_while_receiver_is_waiting_for_user(devices, tmp_path):
    from threading import Thread
    a, b, _, rb, _ = devices
    peer = pair(a, b)
    waiting, release, canceled = Event(), Event(), Event()
    def wait_for_user(*args):
        waiting.set()
        release.wait(3)
        return None
    b.approve_offer = wait_for_user
    source = tmp_path / 'waiting.txt'; source.write_text('do not receive')
    errors = []
    def send():
        try:
            a.send(peer.id, [source], canceled)
        except Exception as exc:
            errors.append(exc)
    worker = Thread(target=send)
    worker.start()
    assert waiting.wait(2)
    canceled.set()
    worker.join(timeout=2)
    release.set()
    assert not worker.is_alive() and len(errors) == 1 and isinstance(errors[0], Cancelled)
    assert not list(rb.iterdir())


def test_corrupted_partial_is_restarted_and_final_data_is_verified(devices, tmp_path):
    a, b, _, rb, _ = devices
    peer = pair(a, b)
    source = tmp_path / 'resume.bin'; source.write_bytes(b'a' * 2000000)
    plan = plan_sources([source]); cancel = Event()
    def stop(message, count):
        if '"advance"' in message:
            cancel.set()
    with pytest.raises(Cancelled):
        a.send(peer.id, [], cancel, stop, plan=plan)
    deadline = time.monotonic() + 3
    while b.offers and time.monotonic() < deadline:
        time.sleep(.01)
    partial = next(rb.glob('.soovee-transfers/*/*.part'))
    with partial.open('r+b') as stream:
        stream.write(b'wrong')
    messages = []
    result = Path(a.send(peer.id, [], report=lambda message, count: messages.append(message), plan=plan))
    assert (result / source.name).read_bytes() == source.read_bytes()
    assert any('Partial data differs' in message for message in messages)


def test_bad_manifest_checksum_and_revoked_active_receive_never_publish(devices, tmp_path):
    from dataclasses import replace
    a, b, _, rb, events = devices
    peer = pair(a, b)
    source = tmp_path / 'content.bin'; source.write_bytes(b'b' * 2000000)
    plan = plan_sources([source]); plan.manifest['items'][0]['sha256'] = '0' * 64
    with pytest.raises(TransferError):
        a.send(peer.id, [], plan=plan)
    assert not list(rb.glob('Soovee-*'))
    assert any('integrity' in event.get('message', '') for event in events)
    def revoke(event):
        if event['kind'] == 'progress':
            b.remove_peer(a.store.id)
    b.event = revoke
    with pytest.raises((OSError, TransferError)):
        a.send(peer.id, [source])
    assert not list(rb.glob('Soovee-*')) and not b.store.peers()


def test_space_failure_unsafe_staging_symlinks_and_duplicate_names(devices, tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace
    a, b, _, rb, _ = devices
    source = tmp_path / 'normal'; source.write_bytes(b'file contents')
    plan = plan_sources([source])
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    with pytest.raises(TransferError, match='free space'):
        ReceiveBundle(rb, a.store.id, plan.manifest, Event())
    duplicate = dict(version=1, items=[dict(plan.manifest['items'][0]), dict(plan.manifest['items'][0], path='NORMAL')])
    with pytest.raises(TransferError, match='conflicting'):
        validate_manifest(duplicate)
    target = tmp_path / 'elsewhere'; target.mkdir()
    receiving = tmp_path / 'unsafe'; receiving.mkdir()
    try:
        (receiving / '.soovee-transfers').symlink_to(target, target_is_directory=True)
        link = tmp_path / 'source-link'; link.symlink_to(source)
    except OSError:
        pytest.skip('Symlink creation is unavailable')
    with pytest.raises(TransferError, match='symbolic'):
        ReceiveBundle(receiving, a.store.id, plan.manifest, Event())
    with pytest.raises(TransferError, match='Symbolic'):
        plan_sources([link])
    assert not list(target.iterdir())


def test_oversized_message_is_rejected_before_body_allocation():
    import socket, struct
    from soovee_commander.lan_protocol import MAX_MESSAGE, receive_message
    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack('!I', MAX_MESSAGE + 1))
        with pytest.raises(TransferError, match='size'):
            receive_message(right)
    finally:
        left.close(); right.close()


def test_device_drive_browses_only_granted_roots_and_copies_both_directions(devices, tmp_path):
    from soovee_commander.device_files import DeviceProvider
    from soovee_commander.providers import LocalProvider
    from soovee_commander.operations import copy_entries
    a, b, ra, rb, _ = devices
    peer = pair(a, b)
    assert DeviceProvider(a, peer.id).list('/') == []
    shared = tmp_path / 'shared'; shared.mkdir(); (shared / 'nested').mkdir()
    (shared / 'nested/file.txt').write_bytes(b'from TV')
    grant = b.shares.add(shared, 'TV files', a.store.id, writable=True)
    provider = DeviceProvider(a, peer.id)
    assert provider.list('/')[0].name == 'TV files'
    assert provider.list('/TV files')[0].name == 'nested'
    local = LocalProvider()
    copy_entries(provider, '/TV files', local, str(ra), provider.list('/TV files'), Event())
    assert (ra / 'nested/file.txt').read_bytes() == b'from TV'
    (rb / 'upload.txt').write_bytes(b'to TV')
    copy_entries(local, str(rb), provider, '/TV files', local.list(str(rb)), Event())
    assert (shared / 'upload.txt').read_bytes() == b'to TV'
    assert provider.location('/TV files') == 'soovee-device://' + peer.id + '/TV%20files'
    b.shares.remove(grant['id'])
    with pytest.raises(TransferError):
        provider.list('/TV files')


def test_shared_root_permissions_escape_role_and_private_keys(devices, tmp_path):
    import io
    from soovee_commander.device_files import DeviceProvider, SharedFolders
    a, b, _, _, _ = devices
    peer = pair(a, b)
    folder = tmp_path / 'read-only'; folder.mkdir(); (folder / 'safe').write_bytes(b'safe')
    b.shares.add(folder, 'ReadOnly', a.store.id)
    provider = DeviceProvider(a, peer.id)
    with pytest.raises(TransferError):
        provider.write_from('/ReadOnly/new', io.BytesIO(b'bad'), lambda count: None)
    assert not (folder / 'new').exists()
    with pytest.raises(TransferError):
        provider.list('/ReadOnly/../outside')
    broad = b.shares.add(tmp_path, 'Broad', a.store.id, writable=True)
    with pytest.raises(TransferError):
        provider.list('/Broad/b')
    # TV defaults to being controlled, while a phone/desktop can operate both ways.
    state = tmp_path / 'tv-role'; state.mkdir()
    assert SharedFolders(state, kind='tv').mode == 'controlled'
    b.shares.set_mode('controller')
    assert provider.list('/') == []
    b.shares.set_mode('both')
    a.shares.set_mode('controlled')
    with pytest.raises(TransferError):
        provider.list('/')


def test_device_drive_rejects_bad_checksum_links_and_replaced_roots(devices, tmp_path):
    from soovee_commander.device_files import DeviceProvider
    from soovee_commander.lan_protocol import send_message, receive_message
    a, b, _, _, _ = devices
    peer = pair(a, b)
    root = tmp_path / 'Shared'; root.mkdir()
    outside = tmp_path / 'secret.txt'; outside.write_bytes(b'private')
    (root / 'link.txt').symlink_to(outside)
    grant = b.shares.add(root, 'Files', a.store.id, writable=True)
    provider = DeviceProvider(a, peer.id)
    assert provider.list('/Files') == []
    with pytest.raises(TransferError):
        provider.read_to('/Files/link.txt', __import__('io').BytesIO(), lambda count: None)
    with a.files_connection(peer.id) as sock:
        send_message(sock, dict(action='put', share=grant['id'], path='bad.txt', size=3, sha256='0' * 64))
        assert receive_message(sock) == {'ready': True}
        sock.sendall(b'bad')
        with pytest.raises(TransferError, match='integrity'):
            receive_message(sock)
    assert not (root / 'bad.txt').exists() and not list(root.glob('.stereo-*'))
    root.rename(tmp_path / 'Moved'); root.mkdir()
    (root / 'unapproved.txt').write_bytes(b'not shared')
    with pytest.raises(TransferError, match='replaced'):
        provider.list('/Files')
    from urllib.parse import urlsplit, unquote
    path = '/Files/spaces # and 100%.txt'
    assert unquote(urlsplit(provider.location(path)).path) == path


def test_device_move_verifies_copy_before_removing_original(devices, tmp_path):
    from soovee_commander.advanced import move_entries
    from soovee_commander.device_files import DeviceProvider
    from soovee_commander.providers import LocalProvider
    a, b, _, _, _ = devices
    peer = pair(a, b)
    root = tmp_path / 'Shared'; root.mkdir()
    (root / 'keep.txt').write_text('keep')
    b.shares.add(root, 'Files', a.store.id, writable=True)
    provider = DeviceProvider(a, peer.id)
    target = tmp_path / 'target'; target.mkdir()
    move_entries(provider, '/Files', LocalProvider(), str(target), provider.list('/Files'), Event())
    assert (target/'keep.txt').read_text()=='keep' and not (root/'keep.txt').exists()


def test_device_rename_delete_permissions_roots_protected_trees_and_no_overwrite(devices,tmp_path):
    from soovee_commander.device_files import DeviceProvider
    from soovee_commander.providers import Entry
    a,b,_,_,_=devices;peer=pair(a,b)
    root=tmp_path/'storage';root.mkdir();(root/'one.txt').write_text('one');(root/'two.txt').write_text('two')
    b.shares.add(root,'Storage',a.store.id,writable=True)
    b.shares.add(root,'ReadOnly',a.store.id,writable=False)
    remote=DeviceProvider(a,peer.id)
    with pytest.raises(TransferError):remote.rename('/Storage/one.txt','/Storage/two.txt')
    assert (root/'two.txt').read_text()=='two'
    with pytest.raises(TransferError):remote.remove('/ReadOnly/one.txt',Entry('one.txt',False))
    with pytest.raises(TransferError):remote.rename('/ReadOnly/one.txt','/ReadOnly/new.txt')
    with pytest.raises(TransferError):remote.remove('/Storage',Entry('Storage',True))
    with pytest.raises(TransferError):remote.rename('/Storage','/Storage/new')
    remote.rename('/Storage/one.txt','/Storage/renamed.txt')
    assert (root/'renamed.txt').read_text()=='one' and not (root/'one.txt').exists()
    (root/'folder/nested').mkdir(parents=True);(root/'folder/nested/file.txt').write_text('delete')
    remote.remove('/Storage/folder',Entry('folder',True))
    assert not (root/'folder').exists()
    (root/'Android/data').mkdir(parents=True);(root/'Android/data/keep').write_text('private')
    b.shares.denied_paths=[root/'Android/data']
    for action in (lambda:remote.remove('/Storage/Android',Entry('Android',True)),
                   lambda:remote.rename('/Storage/Android','/Storage/renamed-Android')):
        with pytest.raises(TransferError):action()
    assert (root/'Android/data/keep').read_text()=='private'
    remote.remove('/Storage/renamed.txt',Entry('renamed.txt',False))
    assert not (root/'renamed.txt').exists()
    assert (root/'two.txt').read_text()=='two'


def test_device_drive_revoked_read_stops_before_publication(devices, tmp_path):
    from soovee_commander.device_files import DeviceProvider
    from soovee_commander.operations import copy_entries
    from soovee_commander.providers import LocalProvider
    a, b, _, _, _ = devices
    peer = pair(a, b)
    root = tmp_path / 'Shared'; root.mkdir()
    (root / 'large.bin').write_bytes(b'x' * (16 * 1024 * 1024))
    grant = b.shares.add(root, 'Files', a.store.id)
    target = tmp_path / 'target'; target.mkdir()
    provider = DeviceProvider(a, peer.id)
    revoked = False
    def revoke(message, count):
        nonlocal revoked
        if count and not revoked:
            revoked = True
            b.shares.remove(grant['id'])
    with pytest.raises((TransferError, OSError)):
        copy_entries(provider, '/Files', LocalProvider(), str(target), provider.list('/Files'), Event(), revoke)
    assert revoked and not list(target.iterdir())


def test_pair_request_makes_the_other_device_show_a_code_without_sending_it(devices):
    import time
    a, b, _, _, events = devices
    assert b.pairing is None
    response = a.request_pairing('127.0.0.1', b.port)
    assert response['showing'] and response['name'] == 'Computer B' and 0 < response['expires'] <= 300
    assert b.pairing is not None and b.pairing['code'] not in str(response)
    deadline = time.monotonic() + 2
    while not any(e['kind'] == 'pair-request' for e in events) and time.monotonic() < deadline:
        time.sleep(.01)
    request = next(e for e in events if e['kind'] == 'pair-request')
    assert request['name'] == 'Computer A' and request['host'] == '127.0.0.1'
    # The code shown on B now pairs A, still with approval on both sides.
    code = b.pairing['code']
    peer = a.pair('127.0.0.1', b.port, code, approve=lambda peer: True)
    assert peer.id == b.store.id and b.store.get(a.store.id)
    # Rapid repeated requests are refused; an active code is reused, not replaced.
    b.begin_pairing(); first = b.pairing['code']
    time.sleep(2.1)
    a.request_pairing('127.0.0.1', b.port)
    assert b.pairing['code'] == first
    with pytest.raises(TransferError):
        a.request_pairing('127.0.0.1', b.port)


def test_removing_a_peer_forgets_its_key_and_shares(devices, tmp_path):
    a, b, _, _, _ = devices
    pair(a, b)
    folder = tmp_path / 'shared'; folder.mkdir()
    b.shares.add(str(folder), 'Shared', a.store.id, writable=True)
    assert b.shares.available(a.store.id)
    b.remove_peer(a.store.id)
    assert not b.shares.available(a.store.id)
    with pytest.raises(Exception):
        b.store.get(a.store.id)


def test_pairing_again_after_one_side_forgot_replaces_the_key_and_drops_old_grants(devices, tmp_path):
    a, b, _, _, _ = devices
    pair(a, b)
    folder = tmp_path / 'old-share'; folder.mkdir()
    b.shares.add(str(folder), 'Old', a.store.id, writable=True)
    old_secret = b.store.get(a.store.id).secret
    a.remove_peer(b.store.id)  # Only A forgets; B still remembers A.
    peer = pair(a, b)          # Used to fail with "Remove the old pairing…".
    assert b.store.get(a.store.id).secret == peer.secret != old_secret
    assert not b.shares.available(a.store.id)  # No grant survives from the old key.


def test_device_that_forgot_the_pairing_is_reported_as_not_recognized(devices, tmp_path):
    from soovee_commander.lan_protocol import PairingNotRecognized
    a, b, _, _, _ = devices
    pair(a, b)
    b.remove_peer(a.store.id)  # B forgot A; A still has B's old key.
    with pytest.raises(PairingNotRecognized):
        with a.files_connection(b.store.id):
            pass
