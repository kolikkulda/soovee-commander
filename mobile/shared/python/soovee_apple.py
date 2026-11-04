"""UIKit callbacks for the same transfer bridge used by the Android client."""
import ctypes
import json
from pathlib import Path
import soovee_mobile as core


class Callbacks:
    def __init__(self):
        native = ctypes.CDLL(None)
        self.approve_native = native.soovee_approve
        self.approve_native.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self.approve_native.restype = ctypes.c_int
        self.event_native = native.soovee_event
        self.event_native.argtypes = [ctypes.c_char_p]
        self.event_native.restype = None

    def approve(self, kind, payload):
        return bool(self.approve_native(kind.encode(), payload.encode()))

    def activity(self, payload):
        self.event_native(payload.encode())


def start(state, shared, name, kind):
    return core.start(state, shared, name, kind, Callbacks())


def call(name, *args):
    function = getattr(core, name)
    try:
        result = function(*args)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception:
        core.logger.exception('Native iOS operation failed: %s', name)
        raise
