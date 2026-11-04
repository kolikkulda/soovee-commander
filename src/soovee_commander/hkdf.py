"""RFC 5869 HKDF-SHA256 using Python's OpenSSL-backed HMAC primitives."""
import hashlib
import hmac


def hkdf_sha256(data, length, *, salt=None, info=b''):
    if not isinstance(length, int) or not 0 <= length <= 255 * 32:
        raise ValueError('Invalid HKDF output length.')
    key = hmac.digest(salt if salt is not None else bytes(32), data, hashlib.sha256)
    blocks, previous = [], b''
    for index in range(1, (length + 31) // 32 + 1):
        previous = hmac.digest(key, previous + info + bytes([index]), hashlib.sha256)
        blocks.append(previous)
    return b''.join(blocks)[:length]
