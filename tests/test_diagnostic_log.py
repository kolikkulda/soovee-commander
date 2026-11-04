import json
import logging
import os

from soovee_commander import diagnostic_log as logs


def test_persistent_tracebacks_are_redacted_before_disk_and_survive_reload(tmp_path):
    try:
        path = logs.configure(tmp_path)
        logs.register_secret('unique-password-7462')
        try:
            raise ValueError('ftp://user:password@example.test/file secret=abc123 unique-password-7462 soovee-transfer://pair?code=12345678')
        except ValueError:
            logs.logger.exception('Transfer failed · id=example')
        for handler in logs.logger.handlers:
            handler.flush()
        text = path.read_text(encoding='utf-8')
        assert 'unique-password-7462' not in text and '12345678' not in text and 'user:password' not in text and 'abc123' not in text
        record = json.loads(text.splitlines()[-1])
        assert 'ValueError' in record['traceback'] and 'id=example' in record['event']
        logs.configure(tmp_path)
        assert 'Transfer failed' in logs.read_tail()
        if os.name != 'nt':  # Windows uses ACLs, not POSIX permission bits.
            assert path.stat().st_mode & 0o077 == 0
    finally:
        for handler in list(logs.logger.handlers):
            handler.close(); logs.logger.removeHandler(handler)
        logs.logger.addHandler(logging.NullHandler())
        logs._path = None
