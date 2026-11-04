"""Structured transfer events shared by workers and the UI."""
import json

PREFIX = "@transfer:"


def emit(report, event, **values):
    report(PREFIX + json.dumps(dict(event=event, **values), ensure_ascii=False), 0)
