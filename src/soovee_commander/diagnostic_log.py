"""Bounded persistent diagnostics, redacted before writing to disk."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import threading
import traceback

logger = logging.getLogger('soovee')
logger.addHandler(logging.NullHandler())
_secrets = set()
_lock = threading.RLock()
_path = None


def register_secret(value):
    if isinstance(value, str) and len(value) >= 4:
        with _lock:
            _secrets.add(value)


def redact(text):
    text = str(text)
    text = re.sub(r'soovee-transfer://[^\s<>"\']+', '[pairing invitation removed]', text, flags=re.I)
    text = re.sub(r'([a-z][a-z0-9+.-]*://)[^/\s@]+@', r'\1[credentials removed]@', text, flags=re.I)
    text = re.sub(r'(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s"\']+', r'\1[redacted]', text, flags=re.I)
    text = re.sub(r'((?:password|passwd|secret|token|pairing[_ -]?code|authorization)["\']?\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^\s,;}]+)', r'\1[redacted]', text, flags=re.I)
    with _lock:
        for secret in sorted(_secrets, key=len, reverse=True):
            text = text.replace(secret, '[redacted]')
    return text


class SafeFormatter(logging.Formatter):
    def format(self, record):
        value = dict(time=self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'), level=record.levelname,
                     thread=record.threadName, event=redact(record.getMessage()))
        if record.exc_info:
            value['traceback'] = redact(''.join(traceback.format_exception(*record.exc_info)))
        return json.dumps(value, ensure_ascii=False)


def configure(directory=None):
    global _path
    if directory is None:
        if sys.platform == 'darwin':
            directory = Path.home() / 'Library/Logs/SooveeCommander'
        elif os.name == 'nt':
            directory = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SooveeCommander/logs'
        else:
            directory = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'soovee-commander/logs'
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        directory.chmod(0o700)
    _path = directory / 'application.jsonl'
    handler = RotatingFileHandler(_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8', delay=True)
    handler.setFormatter(SafeFormatter())
    for previous in list(logger.handlers):
        logger.removeHandler(previous); previous.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    from . import __version__
    logger.info('Application started · version=%s · platform=%s · Python=%s', __version__, sys.platform, sys.version.split()[0])
    if os.name != 'nt':
        _path.chmod(0o600)
    return _path


def log_path():
    return _path


def install_exception_hooks():
    def exception(kind, value, tb):
        logger.critical('Unhandled main-thread exception', exc_info=(kind, value, tb))
    sys.excepthook = exception
    threading.excepthook = lambda args: exception(args.exc_type, args.exc_value, args.exc_traceback)
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    def qt_message(kind, context, message):
        if kind in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            logger.error('Qt · %s', message)
        elif kind == QtMsgType.QtWarningMsg:
            logger.warning('Qt · %s', message)
    qInstallMessageHandler(qt_message)


def read_tail(limit=300000):
    if _path is None or not _path.is_file():
        return ''
    with _path.open('rb') as stream:
        stream.seek(max(0, _path.stat().st_size - limit))
        return stream.read(limit).decode('utf-8', errors='replace')
