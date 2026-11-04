import os
from pathlib import Path
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from soovee_commander.hkdf import hkdf_sha256
from soovee_commander.providers import Entry
from soovee_commander.advanced import rename_names
from soovee_commander.rename_masks import character_range, literal_mask


@pytest.mark.parametrize('specification,expected', [('2-5', 'bcde'), ('2,5', 'bcdef'), ('2-', 'bcdefghij'),
    ('-8,5', 'cdefg'), ('-8-5', 'cdef'), ('2--5', 'bcdef'), ('-5-', 'fghij'), ('1', 'a'), ('-1', 'j')])
def test_tc_character_ranges(specification, expected):
    assert character_range('abcdefghij', specification) == expected


def test_counter_ranges_parent_and_unicode():
    entries = [Entry('žluťoučký.txt', False, 1, 0), Entry('abcdef.txt', False, 1, 0)]
    assert rename_names(entries, '[P]_[N1-3]_[C10+5:3]', parent='/Pictures/Trip') == ['Trip_žlu_010.txt', 'Trip_abc_015.txt']
    assert rename_names(entries, '[C]_[N]', start=7, step=-2, digits=3) == ['007_žluťoučký.txt', '005_abcdef.txt']


def test_source_brackets_do_not_become_placeholders():
    entries = [Entry('[N]_film[1080p].mkv', False, 1, 0)]
    assert rename_names(entries) == [entries[0].name]
    assert rename_names(entries, literal_mask('[C] literal')) == ['[C] literal.mkv']


def test_regex_and_extension_protection():
    entries = [Entry('Photo_12.JPG', False, 1, 0)]
    assert rename_names(entries, find=r'photo_(\d+)', replacement=r'Image-\1', regex=True, case_sensitive=False,
                        replace_extension=False) == ['Image-12.JPG']
    with pytest.raises(ValueError): rename_names(entries, find='[', regex=True)
    with pytest.raises(ValueError): rename_names(entries, '[N0]')


def test_hkdf_matches_rfc5869_sha256_vector():
    assert hkdf_sha256(bytes.fromhex('0b' * 22), 42, salt=bytes.fromhex('000102030405060708090a0b0c'),
                       info=bytes.fromhex('f0f1f2f3f4f5f6f7f8f9')).hex() == (
                           '3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865')


@pytest.mark.parametrize('length,salt', [(0, None), (32, None), (80, b''), (8160, b'custom salt')])
def test_mobile_hkdf_is_identical_to_desktop_dependency(length, salt):
    assert hkdf_sha256(b'input key', length, salt=salt, info=b'soovee.test') == HKDF(
        algorithm=SHA256(), length=length, salt=salt, info=b'soovee.test').derive(b'input key')


def test_android_spake2_interoperates_with_unmodified_desktop():
    from spake2 import SPAKE2_A
    exchange = SPAKE2_A(b'12345678', idA=b'soovee.sender.v1', idB=b'soovee.receiver.v1')
    message = exchange.start()
    source = Path(__file__).parents[1] / 'mobile/shared/python'
    script = '''
import sys,json
sys.path.insert(0,sys.argv[1])
from spake2 import SPAKE2_B
b=SPAKE2_B(b'12345678',idA=b'soovee.sender.v1',idB=b'soovee.receiver.v1')
message=b.start(); key=b.finish(bytes.fromhex(sys.argv[2]))
print(message.hex());print(key.hex())
'''
    # The vendored mobile SPAKE2 imports the shared HKDF from the desktop package.
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path(__file__).parents[1] / 'src'), os.environ.get('PYTHONPATH', '')]))
    result = subprocess.run([sys.executable, '-c', script, str(source), message.hex()], capture_output=True, text=True, check=True, env=env)
    response, key = result.stdout.strip().splitlines()
    assert exchange.finish(bytes.fromhex(response)).hex() == key
