"""Run: QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/benchmark.py"""
import argparse
from datetime import datetime
import json
import hashlib
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
from threading import Event
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QStyle, QTreeView, QTreeWidget, QTreeWidgetItem

from soovee_commander.filemodel import FileModel, size_text
from soovee_commander.providers import Entry, LocalProvider
from soovee_commander.operations import copy_entries
from soovee_commander.qt_runtime import prepare_plugins


class LegacyItem(QTreeWidgetItem):
    """The previous implementation, kept here only for comparable measurements."""
    def __lt__(self, other):
        a, b = self.data(0, Qt.ItemDataRole.UserRole), other.data(0, Qt.ItemDataRole.UserRole)
        column = self.treeWidget().sortColumn()
        if column == 0:
            return (not a.is_dir, a.name.casefold()) < (not b.is_dir, b.name.casefold())
        if column == 1:
            return a.size < b.size
        return a.modified < b.modified


def measure(function):
    start = time.perf_counter()
    function()
    return round(time.perf_counter() - start, 5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--disk", action="store_true")
    parser.add_argument("--transfer", action="store_true")
    parser.add_argument("--output", default="build/performance.json")
    args = parser.parse_args()
    plugin_copy = prepare_plugins()
    app = QApplication([])
    app.setStyle("Fusion")
    entries = [Entry(f"file-{i:06d}.txt", False, i * 1024, 1700000000) for i in range(args.rows)]
    result = {"rows": args.rows, "python": platform.python_version(), "platform": platform.platform(),
              "qt_platform": app.platformName(), "date": datetime.now().date().isoformat(),
              "scope": "Directory model timings exclude disk I/O. Optional disk and copy measurements are reported separately. Warm medians unless stated otherwise."}
    view = QTreeView()
    model = FileModel(view)
    view.setModel(model)
    view.setRootIsDecorated(False)
    view.setUniformRowHeights(True)
    view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    view.resize(650, 500)
    view.show()
    app.processEvents()
    times = []
    for _ in range(3):
        times.append(measure(lambda: (model.set_entries(entries), app.processEvents())))
    result["model_populate_sort_first_paint_seconds"] = statistics.median(times)
    result["filter_first_paint_seconds"] = measure(lambda: (model.set_filter("999"), app.processEvents()))
    model.set_filter("")
    result["numeric_sort_first_paint_seconds"] = measure(lambda: (model.sort(1, Qt.SortOrder.DescendingOrder), app.processEvents()))
    result["scroll_to_last_first_paint_seconds"] = measure(lambda: (view.scrollTo(model.index(model.rowCount()-1, 0)), app.processEvents()))
    view.close()
    if args.legacy:
        legacy = QTreeWidget()
        legacy.setColumnCount(4)
        legacy.setRootIsDecorated(False)
        legacy.setUniformRowHeights(True)
        legacy.resize(650, 500)
        legacy.show()
        app.processEvents()

        def populate():
            for e in entries:
                item = LegacyItem([e.name, size_text(e.size),
                                   datetime.fromtimestamp(e.modified).strftime("%d.%m.%Y %H:%M"), "TXT"])
                item.setData(0, Qt.ItemDataRole.UserRole, e)
                item.setIcon(0, legacy.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                legacy.addTopLevelItem(item)
            legacy.sortItems(0, Qt.SortOrder.AscendingOrder)
            app.processEvents()
        result["legacy_populate_sort_first_paint_seconds"] = measure(populate)
        legacy.close()
    if args.disk:
        with tempfile.TemporaryDirectory(prefix="stereo-benchmark-") as temporary:
            directory = Path(temporary)
            for i in range(args.rows):
                (directory / f"file-{i:06d}.txt").touch()
            provider = LocalProvider()
            scans = []
            for _ in range(3):
                scans.append(measure(lambda: provider.list(temporary)))
            result["real_directory_scan_seconds_warm_median"] = statistics.median(scans)
    if args.transfer:
        with tempfile.TemporaryDirectory(prefix="stereo-transfer-benchmark-") as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "target"
            source.mkdir()
            destination.mkdir()
            block = os.urandom(1024 * 1024)
            path = source / "payload.bin"
            with path.open("wb") as stream:
                for _ in range(128):
                    stream.write(block)
            provider = LocalProvider()
            entries = provider.list(str(source))
            old_times, new_times = [], []
            with path.open("rb") as stream:
                expected = hashlib.file_digest(stream, "sha256").hexdigest()
            for i in range(3):
                old = destination / "legacy.bin"
                def legacy_copy():
                    with tempfile.SpooledTemporaryFile(max_size=8*1024*1024) as buffer:
                        provider.read_to(str(path), buffer, lambda n: None)
                        buffer.seek(0)
                        provider.write_from(str(old), buffer, lambda n: None)
                old_times.append(measure(legacy_copy))
                old.unlink()
                new_times.append(measure(lambda: copy_entries(provider, str(source), provider,
                                  str(destination), entries, Event())))
                with (destination / "payload.bin").open("rb") as stream:
                    assert hashlib.file_digest(stream, "sha256").hexdigest() == expected
                (destination / "payload.bin").unlink()
            result["local_copy_bytes"] = 128 * 1024 * 1024
            result["legacy_staged_copy_seconds_warm_median"] = statistics.median(old_times)
            result["direct_copy_seconds_warm_median"] = statistics.median(new_times)
            result["copy_sha256_verified"] = True
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
