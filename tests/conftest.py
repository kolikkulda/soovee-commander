"""Isolate the process-wide UI language between tests."""
import os

# Widget tests block on a real window server; headless Qt keeps runs deterministic.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from soovee_commander.i18n import set_language


@pytest.fixture(autouse=True)
def english_messages():
    set_language("en")
    yield
    set_language("en")
