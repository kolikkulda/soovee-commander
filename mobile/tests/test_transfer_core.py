"""Headless mobile tests, run with the exact Python version bundled on Android."""
import hashlib
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'mobile/shared/python')]

from soovee_commander.device_files import DeviceProvider
from soovee_commander.lan import TransferService
from soovee_commander.lan_protocol import require_tls_psk, TransferError
from soovee_commander.lan_store import private_directory


class MobileCore(unittest.TestCase):
    def test_native_receive_bundle_without_qt(self):
        from unittest.mock import patch
        with TemporaryDirectory(prefix='soovee-mobile-bundle-') as directory:
            root = Path(directory)
            received = root / 'received'; received.mkdir()
            sender = TransferService(root / 'sender', 'Test sender')
            receiver = TransferService(root / 'receiver', 'Test receiver', approve_pair=lambda peer: True,
                                       approve_offer=lambda *args: received)
            sender.start(); receiver.start()
            try:
                peer = sender.pair('127.0.0.1', receiver.port, receiver.begin_pairing(), approve=lambda peer: True)
                source = root / 'video.mp4'; source.write_bytes(b'native transfer')
                with patch.dict(sys.modules, {'PySide6.QtCore': None}):
                    output = Path(sender.send(peer.id, [source]))
                self.assertEqual((output / source.name).read_bytes(), source.read_bytes())
            finally:
                sender.stop(); receiver.stop()

    def test_python_runtime_pairing_scoped_file_roundtrip(self):
        require_tls_psk()
        with TemporaryDirectory(prefix='soovee-mobile-ci-') as directory:
            root = Path(directory)
            shared = root / 'Shared'; shared.mkdir()
            a = TransferService(root / 'controller', 'Test controller')
            b = TransferService(root / 'tv', 'Test TV', approve_pair=lambda peer: True, device_kind='tv')
            a.start(); b.start()
            try:
                peer = a.pair('127.0.0.1', b.port, b.begin_pairing(), approve=lambda peer: True)
                b.shares.add(shared, 'Shared', a.store.id, writable=True)
                remote = DeviceProvider(a, peer.id)
                self.assertEqual([e.name for e in remote.list('/')], ['Shared'])
                payload = bytes(range(256)) * 12000
                remote.write_from('/Shared/roundtrip.bin', io.BytesIO(payload), lambda count: None)
                output = io.BytesIO()
                remote.read_to('/Shared/roundtrip.bin', output, lambda count: None)
                self.assertEqual(hashlib.sha256(payload).digest(), hashlib.sha256(output.getvalue()).digest())
                remote.mkdir('/Shared/new-folder')
                self.assertTrue((shared / 'new-folder').is_dir())
                with self.assertRaises(TransferError):
                    remote.write_from('/Shared/roundtrip.bin', io.BytesIO(b'overwrite'), lambda count: None)
                self.assertEqual((shared / 'roundtrip.bin').read_bytes(), payload)
            finally:
                a.stop(); b.stop()

    def test_private_state_rejects_symlink_on_older_python(self):
        with TemporaryDirectory(prefix='soovee-mobile-state-') as directory:
            root = Path(directory)
            real = private_directory(root / 'real')
            link = root / 'alias'; link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(TransferError):
                private_directory(link)


if __name__ == '__main__': unittest.main()
