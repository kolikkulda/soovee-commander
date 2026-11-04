from types import SimpleNamespace

import pytest

from soovee_commander.storage import volume_snapshot


def storage(*, total=1000, free=400, available=300, ready=True, readonly=False):
    return SimpleNamespace(rootPath=lambda: '/', displayName=lambda: 'Test volume',
                           isValid=lambda: True, isReady=lambda: ready,
                           bytesTotal=lambda: total, bytesFree=lambda: free,
                           bytesAvailable=lambda: available, isReadOnly=lambda: readonly,
                           fileSystemType=lambda: b'APFS')


def test_volume_separates_user_available_space_from_free_space():
    info = volume_snapshot(storage(readonly=True))
    assert (info.total, info.used, info.free, info.available, info.percent) == (1000, 600, 400, 300, 60)
    assert info.readonly and info.filesystem == 'APFS'


@pytest.mark.parametrize('total,free,available', [(0, 0, 0), (-1, -1, -1), (100, -1, -1), (100, 110, 90), (100, 50, 70)])
def test_unknown_or_invalid_capacity_never_becomes_a_full_or_empty_disk(total, free, available):
    info = volume_snapshot(storage(total=total, free=free, available=available))
    assert info.total is None and info.used is None and info.available is None


def test_unmounted_volume_has_no_snapshot():
    assert volume_snapshot(storage(ready=False)) is None


def test_full_volume_remains_known():
    info = volume_snapshot(storage(free=0, available=0))
    assert info.total == 1000 and info.available == 0 and info.percent == 100
